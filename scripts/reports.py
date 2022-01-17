# Module: reports.py
# Functions to update the database with current period info and generate grade reports etc.

import views # new report classes

from time import ctime # for keeping track of times
from decimal import Decimal, localcontext, ROUND_DOWN # use to truncate grades predictably
from model import Student, Parent, Teacher, Term, GP_Group, Grading_Period, Course, Section, Grade_Record, Attendance, canvas_site, Session, crm_site


def create_db(*,crm_lookup = False):
  # starts a new db from scratch or adds new term info to an existing one
  site = canvas_site()
  term = site.get_current_term()
  
  print(f'Starting at {ctime()} Updating terms')
  site.update_terms()
  
  print(f'@ {ctime()} Updating grading periods')
  site.update_grading_periods()
  
  print(f'@ {ctime()} Updating students')
  site.update_students(crm_lookup = crm_lookup)
  
  print(f'@ {ctime()} Updating teachers')
  site.update_teachers()

  print(f'@ {ctime()} Updating courses from the current term')
  site.update_courses()

  print(f'@ {ctime()} Updating enrollments')
  term.update_enrollments()

  print(f'Finished at {ctime()}')

def update_db_period_records(*,midterm = False, cumulative = False, final = False):
  
  # no such thing as cumulative midterm
  if midterm and cumulative:
    print(f'No such thing as a cumulative midterm')
    return False
  if cumulative:
    periods = canvas_site().get_cumulative_periods()
  else:
    periods = [canvas_site().get_current_period()]
  
  for period in periods:    
    print(f'Starting at {ctime()} Set the comment field name to default')
    period.set_comment_field(midterm)
    
    print(f'@ {ctime()} Updating attendance')
    period.update_attendance()
    
    
    print(f'@ {ctime()} Updating {period.period_name} grade records and comments')
    period.update_grade_records()
  
  if final:
    term = canvas_site().get_current_term()
    print(f'@ {ctime()} Updating {term.term_name} grade records')
    term.update_grade_records()

  print(f'Finished at {ctime()}')