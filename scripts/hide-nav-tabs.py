# Module: hide-nav-tabs.py
from model import Student, Parent, Teacher, Term, GP_Group, Grading_Period, Course, Section, Grade_Record, Attendance, canvas_site, Session, crm_site

def hide_people():
    site = canvas_site()
    term = site.get_current_term()

    session = Session()
    for course in term.courses:
        try:
            course.set_canvas_tab_params(tab_id = "people",hidden = "true")
            print(f'Finished {course.full_name}')
        except Exception as ex:
            print(ex)

    
def hide_collaborations():
    site = canvas_site()
    term = site.get_current_term()

    session = Session()
    for course in term.courses:
        try:
            course.set_canvas_tab_params(tab_id = "collaborations",hidden = "true")
            print(f'Finished {course.full_name}')
        except Exception as ex:
            print(ex)

def hide_discussions():
    site = canvas_site()
    term = site.get_current_term()

    session = Session()
    for course in term.courses:
        try:
            course.set_canvas_tab_params(tab_id = "discussions",hidden = "true")
            print(f'Finished {course.full_name}')
        except Exception as ex:
            print(ex)