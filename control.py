# Module: control.py

import views # new report classes
from model import Student, Parent, Teacher, Term, GP_Group, \
  Grading_Period, Course, Section, Grade_Record, Attendance, \
    Grading_Standard, Account, canvas_site, Session, crm_site

from time import ctime # for keeping track of times

import pandas # export list of students?


def cs_db_rebuild(*,canvas=None,term=None,student_id_limit = 'C00',course_id_limit = '2020CS', cumulative = False,midterm=False,final=False,comments=True):
  if not canvas:
    canvas = canvas_site()
  # can't define term until it exist in db
  db_initialize(site = canvas)
  
  if not term:
    term = canvas.get_current_term()
  
  print(f'@ {ctime()} Updating students')
  canvas.pull_student_canvas_ids(id_limit = student_id_limit)
  
  print(f'@ {ctime()} Updating teachers')
  canvas.update_teachers()

  print(f'@ {ctime()} Updating courses for term {term.term_name}')
  canvas.update_courses(term=term)

  print(f'@ {ctime()} Updating student enrollments')
  term.update_enrollments(teachers=False,id_limit=course_id_limit)

  print(f'@ {ctime()} Updating teacher enrollments')
  term.update_enrollments(students=False,id_limit=course_id_limit)

  print(f'@ {ctime()} Updating period grades')

  db_update_period_records(site=canvas,midterm=midterm,cumulative=cumulative,comments=comments,final=final,course_id_limit=course_id_limit)

def db_full_rebuild(*,canvas = None, crm = None,term = None, update_canvas = False):
  # recreates full db
  if not canvas:
    canvas = canvas_site()
  if not crm:
    crm = crm_site()
  
  db_initialize(site = canvas,crm=crm)

  print(f'@ {ctime()} Updating students')
  crm.pull_students()

  print(f'@ {ctime()} Updating parents')
  crm.update_parents(active = True)
  
  print(f'@ {ctime()} Updating teachers')
  canvas.update_teachers()

  if not term:
    term = canvas.get_current_term()
  
  print(f'@ {ctime()} Updating courses for term {term.term_name}')
  canvas.update_courses(term=term)

  print(f'@ {ctime()} Updating student enrollments')
  term.update_enrollments(teachers=False)

  print(f'@ {ctime()} Updating teacher enrollments')
  term.update_enrollments(students=False)

def db_initialize(site = None,crm=None):
  # creates basic db without student, course, and teacher info
  if not site:
    site = canvas_site()
  if not crm:
    crm = crm_site()
  
  print(f'@ {ctime()} Updating accounts/subaccounts')
  site.update_accounts()

  print(f'@ {ctime()} Updating terms')
  site.update_terms()
  
  print(f'@ {ctime()} Updating grading periods')
  site.update_grading_periods()

  print(f'@ {ctime()} Updating grading standards')
  site.update_grading_standards()

  print(f'@ {ctime()} Updating CRM field info')
  crm.update_custom()

  print(f'Finished basic initilization at {ctime()}')

def db_update_people(*,site = None,crm = None,crm_lookup = False):
  if not site:
    site = canvas_site()
  if not crm:
    crm = crm_site()
  
  print(f'@ {ctime()} Updating students')
  crm.pull_students()
  site.pull_student_canvas_ids(crm = crm)

  if crm_lookup:
    print(f'@ {ctime()} Updating parents')
    crm.update_parents()
  
  print(f'@ {ctime()} Updating teachers')
  site.update_teachers()

  print(f'Finished updating people at {ctime()}')

def db_update_courses(site = None,*,term = None):
  if not site:
    site = canvas_site()
  if not term:
    term = site.get_current_term()
  
  print(f'@ {ctime()} Updating courses for term {term.term_name}')
  site.update_courses(term=term)


def db_update_enrollments(site = None,*,term = None):
  if not site:
    site = canvas_site()
  if not term:
    term = site.get_current_term()
  
  print(f'@ {ctime()} Updating student enrollments')
  term.update_enrollments(teachers=False)

  print(f'@ {ctime()} Updating teacher enrollments')
  term.update_enrollments(students=False)

  print(f'Finished enrollments at {ctime()}')

def db_update_period_records(site = None,*,period = None,midterm = False, cumulative = False, final = False, comments = True, course_id_limit = '2020'):
  
  if not site:
    site = canvas_site()
  if not period:
    period = site.get_current_period()
  
  # no such thing as cumulative midterm
  if midterm and cumulative:
    print(f'No such thing as a cumulative midterm')
    return False
  if cumulative:
    periods = site.get_cumulative_periods(period=period)
  else:
    periods = [period]
  
  for period in periods:    
    print(f'Starting at {ctime()} Set the comment field name to default')
    period.set_comment_field(midterm)
    
    print(f'@ {ctime()} Updating attendance')
    period.update_attendance()
    
    
    print(f'@ {ctime()} Updating {period.period_name} grade records and comments')
    period.update_grade_records(comments=comments,id_limit = course_id_limit)
  
  if final:
    term = canvas_site().get_current_term()
    print(f'@ {ctime()} Updating {term.term_name} grade records')
    term.update_grade_records()
    print(f'Finished with {term.term_name} grades at {ctime()}')

def db_full_update(site=None,*,comments = True, crm = None, crm_lookup = True):
  if not site:
    site = canvas_site()

  db_initialize(site=site,crm=crm)
  db_update_people(site=site,crm=crm, crm_lookup=crm_lookup)
  
  # all terms ?!?
  session = Session()
  terms = session.query(Term).filter(Term.gp_group_id.isnot(None)).all()
  for term in terms:
    db_update_courses(site=site,term=term)
    db_update_enrollments(site=site,term=term)

    # cumulative and final for Trimester 3
    for period in term.gp_group.grading_periods:
      if period.period_name == 'Trimester 3':
        db_update_period_records(site=site,period=period,cumulative=True,final=True,comments=comments)

  print(f'Finished at full update at {ctime()}')



def set_new_student_ids(*,starts_with='s1',canvas=None, crm=None):
    # start by searching crm for "Current Student" School Status
    # check each child in each family for that status and then check if they have a student ID
    # deduplication needs a separate process - let's give everyone a unique id
    # duplicates can be changed manually or we can make a separate function to check for them
    if not canvas:
      canvas = canvas_site()
    if not crm:
      crm = crm_site()

    # starts_with length is used multiple times
    sw_len = len(starts_with)

    get_fields = ['School Status','Student ID']
    search_fields = {'School Status':'Current Student'}
    students = crm.get_child_fields(get_fields,search_fields)
    # get starting ID
    crm_id = crm.get_highest_id(starts_with=starts_with)
    canvas_id = canvas.get_highest_id(starts_with=starts_with)
    
    # use the higher ID
    crm_num = int(crm_id[sw_len:])
    canvas_num = int(canvas_id[sw_len:])
    if crm_num > canvas_num:
      id_len=len(crm_id)
      id_num = crm_num
    else:
      id_len = len(canvas_id)
      id_num = canvas_num


    for family_id,fam_dat in students.items():
      for child_id,child_dat in fam_dat.items():
        # skip any non-students
        if 'Current Student' not in child_dat['School Status']:
          continue
        # skip any with Student ID's
        if child_dat['Student ID']:
          continue
        try:
          # augment id and convert back to string
          id_num += 1
          id_str = str(id_num)
          ex_zeros = ''.join('0' for i in range(id_len-sw_len-len(id_str)))
          new_id = f'{starts_with}{ex_zeros}{id_str}'
          crm.set_custom_field(family_id,'Student ID',child_id,new_id)
        except Exception as e:
          print(e)
          print(f'Error with family {family_id} child {child_id} at Student ID {id_num}')

