# Module: schoolrosters.py
# contains functions/classes printing schedules and rosters from the local db

from school_db import Student, Parent, Teacher, Term, GP_Group, Grading_Period, Course, Section, Grade_Record, Attendance, Session


# Variable for figuring grade levels
# Current term
current_term_name = '2019-2020'
# Pull the correct term from the db ** must be populated from db first
try:
  session = Session()
  current_term = session.query(Term).filter_by(
      term_name=current_term_name).one()
  print(f'Current term is {current_term.term_name}')
except:
  print('Unable to determine current term. Try updating the terms in the database first.')
  current_term = None


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


def write_roster_header(file, course_title, teacher, header_image='School.png'):

    file.write(
        f"<div class=\"roster\">"
        f"<h1>{course_title}"
        f"<img src=\"{header_image}\" style=\"float:left;width:10cm;height:2cm;\"></h1>"
        f"<h2>{teacher} </h2>"
      )
def write_roster_table_header(file):
    file.write(
        "<table>"
            "<thead>"
                "<tr>"
                    "<th class=\"student\">Students</th>"
                    "<th><table class=\"contact\"><tr>"
                        "<th class=\"parents\">Parents</th>"
                        "<th class=\"phone\">Phone</th>"
                        "<th class=\"email\">Email</th>"
                    "</tr></table></th>"
                "</tr>"
            "</thead>"
            "<tbody>"
        )
def write_roster_contact(file, student):
    file.write(
        f"<tr>"
        f"<td class=\"student\">{student.first_name} {student.last_name}</td>"
        "<td><table class=\"contact\">"
    )
    for parent in student.parents:
      #try:
      #  phone = f''
        file.write(
            "<tr>"
            f"<td class=\"parents\">{parent.first_name} {parent.last_name}</td>"
            f"<td class=\"phone\">{parent.phone[0:3]} {parent.phone[3:6]}-{parent.phone[6:]}</td>"
            f"<td class=\"email\">{parent.email}</td>"
            "</tr>"
        )
    file.write(
        f"</table>"
        f"</td>"
        f"</tr>"
        )

def write_roster_table_footer(file):
    file.write(
        "</tbody>"
        "</table>"
        f"</div class=\"roster\">"
        )

def get_course_title(course):

  # First try to extract the Grade level
  try:

    grade=course.sis_account_id[2:]
    if grade == 'K':
      return "Kindergarten"
    elif grade == 'JK':
       return "Junior Kindergarten"
    else:
      grade = int(grade)

    if 1 <= grade <= 6 and 'Latin' not in course.print_name:
      return f'Grade {grade}'  
    else: 
      return course.full_name    
            
  except:
    print(f'Error processing grade level for course {course.full_name} {course.sis_id}')
    return None

def write_html_footer(file):
  file.write("</body></html>")


def write_roster(file,section):
  # get the course title
  course_title = get_course_title(section.course)

  # Teacher (only the first one?)
  try:
    teacher=section.course.teachers[0].teacher_name
  except:
    teacher = 'TBD'
  # Write the header
  write_roster_header(file,course_title, teacher)

  # Start the table
  write_roster_table_header(file)

  # Entry for every student
  for student in section.students:
    write_roster_contact(file, student)
  
  # End the table
  write_roster_table_footer(file)
  
def write_student_rosters(current_term=current_term):
  
  # Open the file for writing
  with open("generated_docs/School-Rosters.html","w") as file:
    # Start the HTML document
    write_html_header(file)
    # get all courses from the current term
    session = Session()
    courses = session.query(Course).filter_by(term_id = current_term.term_id).order_by(Course.sis_id).all()

    # write a roster for each course
    for course in courses:
      # skip all non-homeroom ls courses
      if  course.homeroom:
        for section in course.sections:
          for _i in range(len(section.students)):

            write_roster(file, section)

    # Close out the html
    write_html_footer(file)

def write_teacher_rosters(current_term=current_term):

  # Open the file for writing
  with open("generated_docs/School-Teacher-Rosters.html","w") as file:
    # Start the HTML document
    write_html_header(file)
    # get all courses from the current term
    session = Session()
    courses = session.query(Course).filter_by(term_id = current_term.term_id).order_by(Course.sis_id).all()

    # write a roster for each course
    for course in courses:
      # skip all non-homeroom ls courses
      if  course.homeroom or course.sis_id[6] == 'U':
        for section in course.sections:
         write_roster(file, section)

    # Close out the html
    write_html_footer(file)

def write_latin_rosters(current_term=current_term):

  # Open the file for writing
  with open("generated_docs/School-Latin-Rosters.html","w") as file:
    # Start the HTML document
    write_html_header(file)
    # get all courses from the current term
    session = Session()
    courses = session.query(Course).filter_by(term_id = current_term.term_id).order_by(Course.sis_id).all()

    # write a roster for each course
    for course in courses:
      # skip all non-homeroom ls courses
      if  course.sis_id[6] == 'L' and 'Latin' in course.print_name:
        for section in course.sections:
          write_roster(file, section)

    # Close out the html
    write_html_footer(file)
