# Module user.py

import views # new report classes
from model import Student, Parent, Teacher, Term, GP_Group, \
  Grading_Period, Course, Section, Grade_Record, Attendance, \
    Grading_Standard, Account, canvas_site, Session, crm_site


# add method to student to add to canvas?

# refresh local db from canvas
# pull from CRM
# check local, if exists, update local, update canvas
# if new, add to local, add to canvas

# should I update the 'update students' routine so a crm lookup is complete?
# keeping these things in sync makes me nervous

# how do I handle duplicates? 
# Write all from CRM to local then upload to Canvas?
# maybe include checks for missing names/data?
# that doesn't work with differentiating between students to be updated vs students who need to be created

# I also need to keep CS in mind

# when do I clear out old stuff from the db?
# I can't really remove old students if I want to use them for transcripts/historical 

full_update = False # go through all students or only "Current Students"
id_limit = 's1'
canvas_refresh = True

crm = crm_site()
canvas = canvas_site()
session = Session()

field_list =  ['First Name','Middle Name','Common Name','Last Name','Student ID','House','School Status','Grad Year']

search_dict = {'Student ID':{'>=':id_limit}} # can't do anything without an ID

if canvas_refresh:
  canvas.update_students(crm_lookup=False)


students = crm.get_child_fields(field_list,search_dict)

for family_id,fam_dat in students.items():
  for child_id,child_dat in fam_dat.items():
    # skip without valid ID
    if not id_limit in child_dat['Student ID']:
      continue
    
    # skip if missing common name or last name
    if not child_dat['Common Name'] or not child_dat['Last Name']:
      print(f'Error: family {family_id} missing name info for student {child_dat["Student ID"]}: skipping . . .')
      continue

    # Logic to check if student already exists in DB
    student = session.query(Student).filter_by(sis_id=child_dat['Student ID']).one_or_none()

    # create if it doesn't exist; update if it doesn't match
    if student:
      needs_creation = False
      needs_update = False
      if not student.last_name == child_dat['Last Name']:
        needs_update = True
      elif not student.common_name == child_dat['Common Name']:
        needs_update = True
    else:
      needs_creation  = True

    # always update DB (might have data not needed for Canvas yet)
    # use School Status to determine active or not
    active = False
    if 'Current Student' in child_dat['School Status']:
      active = True
    student = session.merge(Student(
                              sis_id=child_dat['Student ID'],
                              common_name = child_dat['Common Name'],
                              first_name = child_dat['First Name'],
                              middle_name = child_dat['Middle Name'],
                              last_name = child_dat['Last Name'],
                              house = child_dat['House'],
                              active = active,
                              graduation_year = child_dat['Grad Year']))
    # link to parent id even if parent info not yet in DB
    parent = session.merge(Parent(crm_id=family_id))
    if not parent in student.parents:
      student.parents.append(parent)
    
    session.commit()

    # create or update
    if needs_creation and active:
      student.add_to_canvas(canvas = canvas)
    elif needs_update and active:
      student.update_canvas(canvas = canvas)
    if not student.canvas_id:
      student.add_to_canvas(canvas = canvas)

