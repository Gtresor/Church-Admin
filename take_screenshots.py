"""
Screenshot capture script for Church Admin Management System.
Captures all pages required for Chapter 4 documentation.
Prerequisite: Django dev server running at http://127.0.0.1:8000
Login: admin / admin123
"""

import os
import time
import webbrowser
import pyautogui
import requests
from datetime import datetime

# Session for login
session = requests.Session()
BASE_URL = "http://127.0.0.1:8000"
OUTPUT_DIR = r"c:\Users\GISA\OneDrive\Desktop\church\docs\thesis_pack\screenshots"

# Screenshot pages - (filename, title, url, needs_login, login_first)
PAGES = [
    ("01_login_page", "Login Page", "/login/", False, False),
    ("02_member_registration", "Member Registration", "/register/member/", False, False),
    ("03_member_dashboard", "Member Portal", "/portal/member/dashboard/", True, True),
    ("04_baptism_request", "Baptism Request", "/portal/member/baptism/request/", True, True),
    ("05_admin_dashboard", "Admin Dashboard", "/portal/admin/dashboard/", True, True),
    ("06_member_list", "Member List", "/portal/admin/members/", True, True),
    ("07_baptism_list", "Baptism List", "/portal/admin/baptisms/", True, True),
    ("08_wedding_list", "Wedding List", "/portal/admin/weddings/", True, True),
    ("09_dedication_list", "Dedication List", "/portal/admin/dedications/", True, True),
    ("10_admin_calendar", "Calendar", "/portal/admin/calendar/", True, True),
    ("11_admin_reports", "Reports", "/portal/admin/reports/", True, True),
    ("12_certificate_list", "Certificate List", "/portal/admin/certificates/", True, True),
    ("13_officiant_list", "Officiant List", "/portal/admin/officiants/", True, True),
    ("14_user_list", "User Management", "/portal/admin/users/", True, True),
    ("15_baptism_form", "Admin Baptism Form", "/portal/admin/baptisms/create/", True, True),
]

os.makedirs(OUTPUT_DIR, exist_ok=True)

def do_login():
    resp = session.get(f"{BASE_URL}/login/")
    csrf_token = session.cookies.get("csrftoken", "")
    login_resp = session.post(
        f"{BASE_URL}/login/",
        data={"username": "admin", "password": "admin123", "csrfmiddlewaretoken": csrf_token},
        headers={"Referer": f"{BASE_URL}/login/"},
        cookies=session.cookies.get_dict(),
    )
    return "admin_dashboard" in login_resp.text or login_resp.status_code == 200

def take_screenshot(filename, label):
    filepath = os.path.join(OUTPUT_DIR, f"{filename}.png")
    time.sleep(2)  # Wait for page to render
    screenshot = pyautogui.screenshot()
    screenshot.save(filepath)
    print(f"  ✓ Saved: {filepath}  ({label})")
    return filepath

def main():
    print("=" * 60)
    print("Church Admin Management System - Screenshot Capture")
    print(f"Output: {OUTPUT_DIR}")
    print("=" * 60)

    # Test server
    try:
        r = requests.get(f"{BASE_URL}/login/", timeout=5)
        print(f"✓ Server is running (status {r.status_code})")
    except:
        print("✗ Server is not running! Start it with: python manage.py runserver")
        return

    # Login
    print("\nLogging in as admin...")
    if do_login():
        print("✓ Login successful")
    else:
        print("✗ Login failed, trying screenshot anyway...")

    print(f"\nStarting browser windows. DO NOT MOVE YOUR MOUSE during capture.\n")
    time.sleep(2)

    # First open login page
    print("1/15 Opening login page...")
    webbrowser.open(f"{BASE_URL}/login/")
    time.sleep(2)
    pyautogui.hotkey('f11')  # Full screen
    time.sleep(1)
    take_screenshot("01_login_page", "Login Page")

    # Member registration
    print("2/15 Opening member registration...")
    webbrowser.open(f"{BASE_URL}/register/member/")
    time.sleep(2)
    take_screenshot("02_member_registration", "Member Registration")

    # Member dashboard (need to login first)
    print("3/15 Opening member dashboard...")
    webbrowser.open(f"{BASE_URL}/portal/member/dashboard/")
    time.sleep(2)
    take_screenshot("03_member_dashboard", "Member Dashboard")

    # Baptism request
    print("4/15 Opening baptism request...")
    webbrowser.open(f"{BASE_URL}/portal/member/baptism/request/")
    time.sleep(2)
    take_screenshot("04_baptism_request", "Baptism Request")

    # Admin dashboard
    print("5/15 Opening admin dashboard...")
    webbrowser.open(f"{BASE_URL}/portal/admin/dashboard/")
    time.sleep(2)
    take_screenshot("05_admin_dashboard", "Admin Dashboard")

    # Member list
    print("6/15 Opening member list...")
    webbrowser.open(f"{BASE_URL}/portal/admin/members/")
    time.sleep(2)
    take_screenshot("06_member_list", "Member List")

    # Baptism list
    print("7/15 Opening baptism list...")
    webbrowser.open(f"{BASE_URL}/portal/admin/baptisms/")
    time.sleep(2)
    take_screenshot("07_baptism_list", "Baptism List")

    # Wedding list
    print("8/15 Opening wedding list...")
    webbrowser.open(f"{BASE_URL}/portal/admin/weddings/")
    time.sleep(2)
    take_screenshot("08_wedding_list", "Wedding List")

    # Dedication list
    print("9/15 Opening dedication list...")
    webbrowser.open(f"{BASE_URL}/portal/admin/dedications/")
    time.sleep(2)
    take_screenshot("09_dedication_list", "Dedication List")

    # Calendar
    print("10/15 Opening calendar...")
    webbrowser.open(f"{BASE_URL}/portal/admin/calendar/")
    time.sleep(2)
    take_screenshot("10_admin_calendar", "Calendar")

    # Reports
    print("11/15 Opening reports...")
    webbrowser.open(f"{BASE_URL}/portal/admin/reports/")
    time.sleep(2)
    take_screenshot("11_admin_reports", "Reports")

    # Certificate list
    print("12/15 Opening certificate list...")
    webbrowser.open(f"{BASE_URL}/portal/admin/certificates/")
    time.sleep(2)
    take_screenshot("12_certificate_list", "Certificate List")

    # Officiant list
    print("13/15 Opening officiant list...")
    webbrowser.open(f"{BASE_URL}/portal/admin/officiants/")
    time.sleep(2)
    take_screenshot("13_officiant_list", "Officiant List")

    # User list
    print("14/15 Opening user list...")
    webbrowser.open(f"{BASE_URL}/portal/admin/users/")
    time.sleep(2)
    take_screenshot("14_user_list", "User List")

    # Baptism create form
    print("15/15 Opening baptism create form...")
    webbrowser.open(f"{BASE_URL}/portal/admin/baptisms/create/")
    time.sleep(2)
    take_screenshot("15_baptism_form", "Baptism Registration Form")

    print("\n" + "=" * 60)
    print("All screenshots captured!")
    print(f"Saved to: {OUTPUT_DIR}")
    print("=" * 60)

if __name__ == "__main__":
    main()