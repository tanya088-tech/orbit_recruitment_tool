#!/usr/bin/env python3
"""Add recruiters from an AUTHORISED export (licensed LinkedIn/Recruiter export, an Apollo-type provider you hold a contract with,
or your own verified list) to data/hiring_contacts.json. They then show on View details as 'Suggested Recruiter'.

CSV columns: company, name, source (required); designation, linkedin_url (a linkedin.com/in/ link), location, email, phone, retrieved_at.
Usage: python import_hiring_contacts.py recruiters.csv"""
import sys

from processing.hiring_contacts import import_csv

if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    print(import_csv(sys.argv[1]))
