# Module crm.py

from model import Student, Parent, Teacher, Term, GP_Group, Grading_Period, Course, Section, Grade_Record, Attendance, canvas_site, Session, crm_site
from dotenv import load_dotenv
import pandas
# Globals - Gross!
grad_year = 2020 # hard code this because functions in this file are one-off for now

site = crm_site()

# make sure the custom fields are up-to-date
site.update_custom()  
  

def set_grad_years():

  grade_field = site.get_api_field('Current Grade')

  json = {grade_field:{'IS NOT NULL':1},
      "options":{"limit":0},
      'api.CustomValue.get':{'return':grade_field}
      }

  results =  site.api_get(json = json, entity = "Contact")
  # This one filters contacts by those who have a student with a grade level


  # Creating a grad year for everyone
  # Get every contact
  #  * can do contact get - whether I can handle all at once, Im not sure.
  # Get every child from every contact
  #  - field Im looking for is civicrm_value_child_info_1_id ?
  #   - I don't think there is a way to get child id's directly. If I pick a custom field, values are listed with child ids as keys

  #for each child, get grade level, compute grad year, write grad year

  for family_id,family in results['values'].items():
    # all families should have children since the original query was filtered
    child_dat = family['api.CustomValue.get']['values'][0]
    # the crm response has a dict nested in a single item list
    # now remove the extra detritus CiviCRM loves
    junk = ['entity_id','entity_table','latest','id']
    for key in junk:
      del child_dat[key]

    # this could be faster by moving end year lookups here for each family instead of for each child
    # it might take half the time, but it only needs to run once

    # now iterate through keys and values left
    # these should be the child id and grade level, respectively
    for child_id,grade_level in child_dat.items():
      # Skip Null entries
      if not grade_level:
        continue
      # wrap the action in some retries
      attempt = 0
      while attempt < 3:
        try:
          # adjust for wonky crm using 1 for 1st and -1 for K
          grade_level = int(grade_level)
          if grade_level < 1:
            grade_level += 1
          
          # If they have an end year, their grade hasn't been updated since then
          # That end year should become the current_grad_year for calculating stuff

          #######################################
          # This needs to be fixed in case any current students might have an end year. Only use end year for "Former Students" or "Alumni"

          fall_end_year = site.get_child_field(family_id=family_id,child_id=child_id,field_label='End Year')
          if fall_end_year:
            current_grad_year = int(fall_end_year) + 2001 # move from 18 (fall year) to 2019 (full spring year)
          else:
            current_grad_year = None
          grad_year = Student.get_grad_year(grade_level,current_grad_year)
          site.set_custom_field(family_id =family_id,child_id = child_id,field_label='Grad Year',value = grad_year)
          break
        except Exception as e:
          print(e)
          print(f'Error setting Grad Year for family id {family_id} child id {child_id}')
          attempt += 1



# Graduating 12th grade
# look for School status 'Current Student' and Grad Year is now
# set School status to alumni - all others should be dropped
# set grade to null? (I think these are just going to be abandoned)
# set end_year to 19 (for 19-20)
def bump_seniors():
  search = {'School Status':'Current Student','Grad Year':grad_year}
  fields = ['School Status','Grad Year']
  seniors = site.get_child_fields(fields,search)
  for family_id,fam_dat in seniors.items():
    for child_id,child_dat in fam_dat.items():
      # skip any non-seniors
      if not child_dat['Grad Year'] == grad_year:
        continue 
      # skip any non-students?
      if not 'Current Student' in child_dat['School Status']:
        continue

      try:
        # set status
        response = site.set_custom_field(family_id,'School Status',child_id,'Alumni')
        if response['is_error']:
          print(f'unable to to make School Status change to contact {family_id}')
        
        # set end year
        response = site.set_custom_field(family_id,'End Year',child_id,f'{int(grad_year)-2001}')
        if response['is_error']:
          print(f'unable to to make End Year change to contact {family_id}')
      except Exception as e:
        print(e)
        print(f'unable to to make change to contact {family_id}')


# Enrollment:
# ditch old students first:
# New K have enrolled
# returning 1-12 have reenrolled
# search for Current Student - check for re/enrolled
# change current to former
# set end year

def remove_leaving():
  search = {'School Status':'Current Student'}
  fields = ['School Status']
  leaving = site.get_child_fields(fields,search)
  for family_id,fam_dat in leaving.items():
    for child_id,child_dat in fam_dat.items():
      # skip any non-students?
      if not 'Current Student' in child_dat['School Status']:
        continue
      # skip any new/returning students
      if 'Enrolled' in child_dat['School Status'] or 'Reenrolled' in child_dat['School Status']:
        continue
      try:
        # change "Current Student" to "Former Student" in status list
        new_status = ['Former Student' if i=='Current Student' else i for i in child_dat['School Status']]
        # set status
        response = site.set_custom_field(family_id,'School Status',child_id,new_status)
        if response['is_error']:
          print(f'unable to to make School Status change to contact {family_id}')
        
        # set end year
        response = site.set_custom_field(family_id,'End Year',child_id,f'{int(grad_year)-2001}')
        if response['is_error']:
          print(f'unable to to make End Year change to contact {family_id}')
      except Exception as e:
        print(e)
        print(f'unable to to make change to contact {family_id}')


# current student and enrolled = JK moving to K
# status should remove enroll

def cleanup_enrolled():
  # remove enrolled and set Current Student if not already set
  search = {'School Status':'Enrolled'}
  fields = ['School Status']
  enrolled = site.get_child_fields(fields,search)
  for family_id,fam_dat in enrolled.items():
    for child_id,child_dat in fam_dat.items():
      # skip any siblings
      if not 'Enrolled' in child_dat['School Status']:
        continue
      
      # remove "current student" (shouldn't be necessary except JK)
      if 'Current Student' in child_dat['School Status']:
        child_dat['School Status'].remove('Current Student')
        print(f'Family {family_id} had an enrolled/current student')
      # change enrolled to current student
      new_status = ['Current Student' if i=='Enrolled' else i for i in child_dat['School Status']]
      try:
        # set status
        response = site.set_custom_field(family_id,'School Status',child_id,new_status)
        if response['is_error']:
          print(f'unable to to make School Status change to contact {family_id}')
        
      except Exception as e:
        print(e)
        print(f'unable to to make change to contact {family_id}')  

def cleanup_reenrolled():
  # remove enrolled and set Current Student if not already set

  search = {'School Status':'Reenrolled'}
  fields = ['School Status']
  reenrolled = site.get_child_fields(fields,search)
  for family_id,fam_dat in reenrolled.items():
    for child_id,child_dat in fam_dat.items():
      # skip any siblings
      if not 'Reenrolled' in child_dat['School Status']:
        continue
      
      if 'Current Student' in child_dat['School Status']:
        child_dat['School Status'].remove('Current Student')
        
      else:
        print(f'Family {family_id} reenrolled without being a student')
      # change enrolled to current student
      new_status = ['Current Student' if i=='Reenrolled' else i for i in child_dat['School Status']]
      try:
        # set status
        response = site.set_custom_field(family_id,'School Status',child_id,new_status)
        if response['is_error']:
          print(f'unable to to make School Status change to contact {family_id}')
        
      except Exception as e:
        print(e)
        print(f'unable to to make change to contact {family_id}') 

def increment_grades():
  # get all non-null grade levels
  grad_year = 2021 # for next year
  search = {'Current Grade':{'IS NOT NULL':1}}
  fields = ['Current Grade','Grad Year']
  students = site.get_child_fields(fields,search)
  for family_id,fam_dat in students.items():
    for child_id,child_dat in fam_dat.items():
      # skip any blank children
      if not child_dat['Grad Year']:
        continue

      crm_grad_year = int(child_dat['Grad Year'])
      crm_grade = int(child_dat['Current Grade'])
      student_grade = Student.get_grade_level(crm_grad_year,grad_year)
      # adjust for wonky k/jk
      if student_grade < 1:
        student_grade -= 1

      # skip where grade is already updated
      if crm_grade == student_grade:
        print(f'Family {family_id} has child where grade is already incremented?')
        continue 
      
      try:
        # set Current Grade
        response = site.set_custom_field(family_id,'Current Grade',child_id,student_grade)
        if response['is_error']:
          print(f'unable to to make Current Grade change to contact {family_id}')

      except Exception as e:
        print(e)
        print(f'unable to to make change to contact {family_id}')

def move_9th():
  # grad year for rising 9th (still 8)
  grad_9 = Student.get_grad_year(8)
  search = {'Grad Year':grad_9,'School Status':'Current Student'}
  fields = ['School Status','Grad Year','Campus']
  students = site.get_child_fields(fields,search)
  for family_id,fam_dat in students.items():
    for child_id,child_dat in fam_dat.items():
      # skip any non School children
      if 'Current Student' not in child_dat['School Status']:
        continue
      # skip where Campus is already SM
      if child_dat['Campus'] == 'SM':
        continue 
      # only move 9th grade!!!!!!!!!!
      if child_dat['Grad Year'] == grad_9:
        try:
          # set Current Grade
          response = site.set_custom_field(family_id,'Campus',child_id,'SM')
          if response['is_error']:
            print(f'unable to to make Campus change to contact {family_id}')

        except Exception as e:
          print(e)
          print(f'unable to to make change to contact {family_id}')

def check_grades():
  # get all non-null grade levels
  grad_year = 2021 # for next year
  search = {'Current Grade':{'IS NOT NULL':1}}
  fields = ['Current Grade','Grad Year','Common Name','School Status']
  students = site.get_child_fields(fields,search)
  for family_id,fam_dat in students.items():
    for child_id,child_dat in fam_dat.items():
      # skip any blank children
      if child_dat['Current Grade'] and not child_dat['Grad Year']:
        print(f'Error with family {family_id}: {child_dat["Common Name"]} has grade but no grad year')
        continue
      elif not child_dat['Current Grade']:
        continue

      crm_grad_year = int(child_dat['Grad Year'])
      crm_grade = int(child_dat['Current Grade'])
      student_grade = Student.get_grade_level(crm_grad_year,grad_year)
      # adjust for wonky k/jk
      if student_grade < 1:
        student_grade -= 1
      
      if not student_grade == student_grade:
        print(f'Error with family {family_id}: {child_dat["Common Name"]} grade does not match grad year')

      if 'Current Student' in child_dat['School Status'] and not child_dat['Current Grade']:
        print(f'Error with family {family_id}: {child_dat["Common Name"]} missing grade')

      if 'Current Student' in child_dat['School Status'] and not child_dat['Grad Year']:
        print(f'Error with family {family_id}: {child_dat["Common Name"]} missing grad year')


def export():
  # get all non-null grade levels
  grad_year = 2021 # for next year
  search = {'Current Grade':{'IS NOT NULL':1}}
  fields = ['Current Grade','Grad Year','Common Name','Last Name','School Status']
  data = site.get_child_fields(fields,search)
  students = []
  for family_id,fam_dat in data.items():
    for child_id,child_dat in fam_dat.items():
      students.append(child_dat)
  students_df = pandas.DataFrame(students)
  students_df.to_excel('crmtest.xlsx','CRM Data')

def export_crm_duplicates(crm=None):
  if not crm:
    crm = crm_site()


  field_list = ['First Name','Common Name','Last Name','Student ID','Grad Year','Birthday','School Status']
  search_dict = {'Student ID':{'IS NOT NULL':1}}
  student_list = []
  students = crm.get_child_fields(field_list,search_dict)
  for family_id,fam_dat in students.items():
    for child_id,child_dat in fam_dat.items():
      child_dat['child_id']=child_id
      child_dat['family_id']=family_id
      student_list.append(child_dat)

  student_df = pandas.DataFrame(student_list)
  full_name_dup = student_df[student_df.duplicated(subset=['First Name','Last Name','Common Name'],keep=False)]
  last_name_birth_dup = student_df[student_df.duplicated(subset=['Birthday','Last Name'],keep=False)]

  full_name_dup.to_excel('full_name_dup.xlsx','CRM Data')
  last_name_birth_dup.to_excel('birthday_dup.xlsx','CRM Data')

def updates_for_2020_2021():
  set_grad_years()
  print("Done setting grad years")
  bump_seniors()
  print("Done with seniors")
  remove_leaving()
  print("Done with leaving students")
  cleanup_enrolled()
  print("Done with new students")
  cleanup_reenrolled()
  print("Done with returning students")
  move_9th()
  print("Done moving 9th")
  increment_grades()
  print("Done setting grade levels")