# Module: printslips.py
# contains functions/classes printing schedules and rosters from the local db

from school_db import Student, Parent, Teacher, Term, GP_Group, Grading_Period, Course, Section, Grade_Record, Attendance, Session
from dotenv import load_dotenv
from os import getenv
load_dotenv()

def write_html_header(file, css='School.css'):
    # Takes open file for writing and optional css url
    # writes the header template and body open tag
    file.write(
            f"<!DOCTYPE html>"
            f"<html>"
            f"<head>"
            f"<link rel=\"stylesheet\" href=\"{css}\">"
            f"<meta charset=UTF-8>"
            f"</head>"
            f"<body>")


def write_slip_header(file, family):

    file.write(
        f"<div class=\"roster\">"
        f"<h1>{family}</h1>"
      )
def write_slip_table_header(file):
    file.write(
        "<table>"
            "<thead>"
                "<tr>"
                    "<th>Students</th>"
                    "<th>Grade</th>"
                    "<th>Campus</th>"
                    "<th>Teacher</th>"
                "</tr>"
            "</thead>"
            "<tbody>"
        )

def get_grade(student):
  try:
    grade_num = 12-student.graduation_year+current_grad_year
    if 1 <= grade_num <=12:
      return grade_num
    elif grade_num == 0:
      return 'K'
    elif grade_num == -1:
      return 'JK'
    else:
      return '?'
  except:
    print(f'Grade Error with {student.first_name} {student.last_name}')
    return None

def write_slip_students(file, parent):
  try:
    parent.students.sort(key = lambda st: st.graduation_year, reverse = True)
  except:
    print(f'Unable to sort students for {parent.first_name} {parent.last_name}')    
  for student in parent.students:
    if not student.graduation_year:
      continue
    file.write(
      f"<tr>"
      f"<td>{student.first_name} {student.last_name}</td>"
      f"<td>{get_grade(student)}</td>"
      )
    for section in student.sections:
      if section.course.homeroom:
        file.write(
          f"<td>{section.course.sis_id[4:6]}</td>"
          f"<td>{section.course.teachers[0].teacher_name}</td>"
          )
    file.write(
        "</tr>"
    )

def write_slip_table_footer(file):
    file.write(
        "</tbody>"
        "</table>"
        f"</div>"
        )

def write_html_footer(file):
  file.write("</body></html>")


def write_slip(file,parent):

  # Write the header
  write_slip_header(file,f'{parent.first_name} {parent.last_name}')

  # Start the table
  write_slip_table_header(file)

  # Write every student
  
  write_slip_students(file, parent)
  
  # End the table
  write_slip_table_footer(file)
  
def write_slips(current_term=current_term):
  
  # Open the file for writing
  with open("generated_docs/School-Slips.html","w") as file:
    # Start the HTML document
    write_html_header(file)
    # get all parents -- this will need to be updated to limit it by year or active students
    session = Session()
    parents = session.query(Parent).order_by(Parent.last_name).all()

    # write a slip for each parent
    for parent in parents:
    # I don't want any old parents
      current = False
      for student in parent.students:
        for section in student.sections:
          
          if section.course.sis_id[0:4] == '2019':
            current = True
      if current  == True:    
        write_slip(file, parent)

    # Close out the html
    write_html_footer(file)