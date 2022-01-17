# Module: schoolschedules.py
# contains functions/classes printing schedules from the local db

from school_db import Student, Parent, Teacher, Term, GP_Group, Grading_Period, Course, Grade_Record, Attendance, Session
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


def write_schedule_header(file, student_name, current_term = current_term, header_image='School.png'):

    file.write(
        f"<div class=\"schedule\">"
        f"<h1>{student_name}"
        f"<img src=\"{header_image}\" style=\"float:left;width:10cm;height:2cm;\"></h1>"
        f"<h2>{current_term.term_name} </h2>"
      )
def write_schedule_table_header(file):
    file.write(
        "<table>"
            "<thead>"
                "<tr>"
                    "<th class=\"course\">Course</th>"
                    "<th class=\"teacher\">Teacher</th>"
                "</tr>"
            "</thead>"
            "<tbody>"
        )
def write_schedule_course(file, course):
  try:
    course_name = course.print_name
  except:
    course_name = None
    print(f'Unable to get name for course {course.sis_id}')
  try:
    teacher_name = course.teachers[0].teacher_name
  except:
    teacher_name = None
    print(f'Unable to get teacher for course {course.sis_id}')  
  file.write(
        f"<tr>"
        f"<td class=\"course\">{course_name}</td>"
        f"<td class=\"teacher\">{teacher_name}</td>"
        f"</tr>"
    )

def write_schedule_table_footer(file):
    file.write(
        "</tbody>"
        "</table>"
        f"</div class=\"schedule\">"
        )

def write_html_footer(file):
  file.write("</body></html>")


def write_schedule(file,student, current_term = current_term):

  # Student name
  student_name = f'{student.first_name} {student.last_name}'
  # Write the header
  write_schedule_header(file, student_name)

  # Start the table
  write_schedule_table_header(file)

  # Entry for every course in the current term
  course_list=[]
  for section in student.sections:
    if section.course.term_id == current_term.term_id:
      course_list.append(section.course) # add the course to our print list

  course_list.sort(key = lambda crs: crs.print_name) # sort the courses by print name before generating html
  for course in course_list:  
    write_schedule_course(file, course)
  
  # End the table
  write_schedule_table_footer(file)
  
def write_schedules(current_term=current_term):
  
  # Open the file for writing
  with open("generated_docs/School-schedules.html","w") as file:
    # Start the HTML document
    write_html_header(file)
    # get 7-12 students
    session = Session()
    students = session.query(Student).filter(Student.graduation_year < 12 - 6 + current_grad_year).order_by(Student.last_name).all()

    # write a schedule for each student
    for student in students:
      if student.sis_id[0] in ['S','s']:
        write_schedule(file, student)

    # Close out the html
    write_html_footer(file)
