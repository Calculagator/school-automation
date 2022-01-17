# HLSIS

## Create a virtual environment
```
#create the virtual environment (once)
python3 -m venv venv

#activate the virtual environment (VisualStudioCode does this automatically)
source venv/bin/activate
```

## Install needed modules

## Modules needed
I've moved all of these to requirements.txt
```
pip install -r requirements.txt
```

## What to do for user accounts
* pull full student info from CRM and Canvas
* Generate student emails (these aren't stored anywhere besides old Canvas)

* create/update student accounts to use google and email


* export a list of students to import into google
  - remove active accounts from import list
  - need a way to indicate which are already active to not give bad instructions
  - need way to select only one parent if multiple but should still email both


- can I use the last login info to identify those who don't need to be updated?

get all active students from crm: common name, last name, student id, grad year, start year?
  get parent info from crm: email, phone, name
    generate student email (and password?)
    write to local db
        lookup student in canvas - if exists
    write student to canvas
    create/update student login for canvas
      generate pw?
    ?create/update observer account?
