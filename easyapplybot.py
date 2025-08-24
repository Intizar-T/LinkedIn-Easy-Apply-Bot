from __future__ import annotations

import json
import csv
import logging
import os
import platform
import random
import re
import stat
import time
from datetime import datetime, timedelta
import getpass
from pathlib import Path

import pandas as pd
import pyautogui
import yaml
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from selenium.webdriver.chrome.service import Service as ChromeService
import webdriver_manager.chrome as ChromeDriverManager
ChromeDriverManager = ChromeDriverManager.ChromeDriverManager


log = logging.getLogger(__name__)


def setupLogger() -> None:
    dt: str = datetime.strftime(datetime.now(), "%m_%d_%y %H_%M_%S ")

    if not os.path.isdir('./logs'):
        os.mkdir('./logs')

    # TODO need to check if there is a log dir available or not
    logging.basicConfig(filename=('./logs/' + str(dt) + 'applyJobs.log'), filemode='w',
                        format='%(asctime)s::%(name)s::%(levelname)s::%(message)s', datefmt='./logs/%d-%b-%y %H:%M:%S')
    log.setLevel(logging.DEBUG)
    c_handler = logging.StreamHandler()
    c_handler.setLevel(logging.DEBUG)
    c_format = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', '%H:%M:%S')
    c_handler.setFormatter(c_format)
    log.addHandler(c_handler)


class EasyApplyBot:
    setupLogger()
    # MAX_SEARCH_TIME is 10 hours by default, feel free to modify it
    MAX_SEARCH_TIME = 60 * 60

    def __init__(self,
                 username,
                 password,
                 phone_number,
                 # profile_path,
                 salary,
                 rate,
                 uploads={},
                 filename='output.csv',
                 blacklist=[],
                 blackListTitles=[],
                 experience_level=[],
                 max_applications=50,
                 min_salary_yearly=60000,
                 min_salary_hourly=32,
                 send_recruiter_invites=True,
                 skip_zero_experience=True,
                 use_linkedin_resume=True
                 ) -> None:

        log.info("Welcome to Easy Apply Bot")
        dirpath: str = os.getcwd()
        log.info("current directory is : " + dirpath)
        log.info("Please wait while we prepare the bot for you")
        if experience_level:
            experience_levels = {
                1: "Entry level",
                2: "Associate",
                3: "Mid-Senior level",
                4: "Director",
                5: "Executive",
                6: "Internship"
            }
            applied_levels = [experience_levels[level] for level in experience_level]
            log.info("Applying for experience level roles: " + ", ".join(applied_levels))
        else:
            log.info("Applying for all experience levels")
        

        self.uploads = uploads
        self.salary = salary
        self.rate = rate
        # self.profile_path = profile_path
        past_ids: list | None = self.get_appliedIDs(filename)
        self.appliedJobIDs: list = past_ids if past_ids != None else []
        self.filename: str = filename
        self.options = self.browser_options()
        try:
            # Try to use ChromeDriverManager first
            self.browser = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=self.options)
        except Exception as e:
            log.warning(f"ChromeDriverManager failed: {e}")
            try:
                # Try using system ChromeDriver
                self.browser = webdriver.Chrome(options=self.options)
            except Exception as e2:
                log.error(f"System ChromeDriver also failed: {e2}")
                # Try using the local assets ChromeDriver
                system = platform.system().lower()
                if system == "darwin":
                    chromedriver_path = "./assets/chromedriver_darwin"
                elif system == "linux":
                    chromedriver_path = "./assets/chromedriver_linux"
                else:
                    chromedriver_path = "./assets/chromedriver_windows"
                
                # Make it executable
                if os.path.exists(chromedriver_path):
                    os.chmod(chromedriver_path, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
                    self.browser = webdriver.Chrome(service=ChromeService(chromedriver_path), options=self.options)
                else:
                    raise Exception("No valid ChromeDriver found")
        self.wait = WebDriverWait(self.browser, 30)
        self.blacklist = blacklist
        self.blackListTitles = blackListTitles
        self.start_linkedin(username, password)
        self.phone_number = phone_number
        self.experience_level = experience_level
        self.max_applications = max_applications
        self.applications_count = 0
        self.min_salary_yearly = min_salary_yearly
        self.min_salary_hourly = min_salary_hourly
        self.send_recruiter_invites = send_recruiter_invites
        self.skip_zero_experience = skip_zero_experience
        self.use_linkedin_resume = use_linkedin_resume


        self.locator = {
            "next": (By.CSS_SELECTOR, "button[aria-label='Continue to next step']"),
            "review": (By.CSS_SELECTOR, "button[aria-label='Review your application']"),
            "submit": (By.CSS_SELECTOR, "button[aria-label='Submit application']"),
            "error": (By.CLASS_NAME, "artdeco-inline-feedback__message"),
            "upload_resume": (By.XPATH, "//*[contains(@id, 'jobs-document-upload-file-input-upload-resume')]"),
            "upload_cv": (By.XPATH, "//*[contains(@id, 'jobs-document-upload-file-input-upload-cover-letter')]"),
            "follow": (By.CSS_SELECTOR, "label[for='follow-company-checkbox']"),
            "upload": (By.NAME, "file"),
            "search": (By.CLASS_NAME, "jobs-search-results-list"),
            "links": ("xpath", '//div[@data-job-id]'),
            "fields": (By.CLASS_NAME, "jobs-easy-apply-form-section__grouping"),
            "radio_select": (By.CSS_SELECTOR, "input[type='radio']"), #need to append [value={}].format(answer)
            "multi_select": (By.XPATH, "//*[contains(@id, 'text-entity-list-form-component')]"),
            "text_select": (By.CLASS_NAME, "artdeco-text-input--input"),
            "2fa_oneClick": (By.ID, 'reset-password-submit-button'),
            "easy_apply_button": (By.XPATH, '//button[contains(@class, "jobs-apply-button")]')

        }

        #initialize questions and answers file
        self.qa_file = Path("qa.csv")
        self.answers = {}

        #if qa file does not exist, create it
        if self.qa_file.is_file():
            df = pd.read_csv(self.qa_file)
            for index, row in df.iterrows():
                self.answers[row['Question']] = row['Answer']
        #if qa file does exist, load it
        else:
            df = pd.DataFrame(columns=["Question", "Answer"])
            df.to_csv(self.qa_file, index=False, encoding='utf-8')


    def get_appliedIDs(self, filename) -> list | None:
        try:
            df = pd.read_csv(filename,
                             header=None,
                             names=['timestamp', 'jobID', 'job', 'company', 'attempted', 'result'],
                             lineterminator='\n',
                             encoding='utf-8')

            df['timestamp'] = pd.to_datetime(df['timestamp'], format="%Y-%m-%d %H:%M:%S")
            df = df[df['timestamp'] > (datetime.now() - timedelta(days=2))]
            jobIDs: list = list(df.jobID)
            log.info(f"{len(jobIDs)} jobIDs found")
            return jobIDs
        except Exception as e:
            log.info(str(e) + "   jobIDs could not be loaded from CSV {}".format(filename))
            return None

    def browser_options(self):
        options = webdriver.ChromeOptions()
        options.add_argument("--start-maximized")
        options.add_argument("--ignore-certificate-errors")
        options.add_argument('--no-sandbox')
        options.add_argument("--disable-extensions")
        #options.add_argument(r'--remote-debugging-port=9222')
        #options.add_argument(r'--profile-directory=Person 1')

        # Disable webdriver flags or you will be easily detectable
        options.add_argument("--disable-blink-features")
        options.add_argument("--disable-blink-features=AutomationControlled")

        # Load user profile
        #options.add_argument(r"--user-data-dir={}".format(self.profile_path))
        return options

    def start_linkedin(self, username, password) -> None:
        log.info("Logging in.....Please wait :)  ")
        self.browser.get("https://www.linkedin.com/login?trk=guest_homepage-basic_nav-header-signin")
        try:
            # Wait for page to load
            time.sleep(3)
            
            user_field = self.browser.find_element(By.ID, "username")
            pw_field = self.browser.find_element(By.ID, "password")
            
            # Try multiple selectors for the login button
            login_button = None
            login_selectors = [
                (By.XPATH, "//button[@type='submit']"),
                (By.XPATH, "//button[contains(@class, 'sign-in-form__submit')]"),
                (By.XPATH, "//button[contains(text(), 'Sign in')]"),
                (By.CSS_SELECTOR, "button[type='submit']"),
                (By.XPATH, '//*[@id="organic-div"]/form/div[3]/button')
            ]
            
            for selector_type, selector_value in login_selectors:
                try:
                    login_button = self.browser.find_element(selector_type, selector_value)
                    break
                except:
                    continue
            
            if not login_button:
                raise Exception("Login button not found")
            
            user_field.clear()
            user_field.send_keys(username)
            user_field.send_keys(Keys.TAB)
            time.sleep(2)
            pw_field.clear()
            pw_field.send_keys(password)
            time.sleep(2)
            login_button.click()
            time.sleep(15)
            # if self.is_present(self.locator["2fa_oneClick"]):
            #     oneclick_auth = self.browser.find_element(by='id', value='reset-password-submit-button')
            #     if oneclick_auth is not None:
            #         log.info("additional authentication required, sleep for 15 seconds so you can do that")
            #         time.sleep(15)
            # else:
            #     time.sleep()
        except TimeoutException:
            log.info("TimeoutException! Username/password field or login button not found")

    def fill_data(self) -> None:
        self.browser.set_window_size(1, 1)
        self.browser.set_window_position(2000, 2000)

    def start_apply(self, positions, locations) -> None:
        start: float = time.time()
        self.fill_data()
        self.positions = positions
        self.locations = locations
        combos: list = []
        while len(combos) < len(positions) * len(locations):
            position = positions[random.randint(0, len(positions) - 1)]
            location = locations[random.randint(0, len(locations) - 1)]
            combo: tuple = (position, location)
            if combo not in combos:
                combos.append(combo)
                log.info(f"Applying to {position}: {location}")
                location = "&location=" + location
                self.applications_loop(position, location)
            if len(combos) > 500:
                break

    # self.finish_apply() --> this does seem to cause more harm than good, since it closes the browser which we usually don't want, other conditions will stop the loop and just break out

    def applications_loop(self, position, location):

        count_application = 0
        count_job = 0
        jobs_per_page = 0
        start_time: float = time.time()

        log.info("Looking for jobs.. Please wait..")

        self.browser.set_window_position(1, 1)
        self.browser.maximize_window()
        self.browser, _ = self.next_jobs_page(position, location, jobs_per_page, experience_level=self.experience_level)
        log.info("Looking for jobs.. Please wait..")

        while time.time() - start_time < self.MAX_SEARCH_TIME and self.applications_count < self.max_applications:
            try:
                log.info(f"{(self.MAX_SEARCH_TIME - (time.time() - start_time)) // 60} minutes left in this search")
                log.info(f"Applications submitted: {self.applications_count}/{self.max_applications}")

                # sleep to make sure everything loads, add random to make us look human.
                randoTime: float = random.uniform(2.0, 4.5)
                log.debug(f"Sleeping for {round(randoTime, 1)}")
                time.sleep(randoTime)
                self.load_page(sleep=0.5)

                # LinkedIn displays the search results in a scrollable <div> on the left side, we have to scroll to its bottom

                # scroll to bottom

                if self.is_present(self.locator["search"]):
                    scrollresults = self.get_elements("search")
                    #     self.browser.find_element(By.CLASS_NAME,
                    #     "jobs-search-results-list"
                    # )
                    # Selenium only detects visible elements; if we scroll to the bottom too fast, only 8-9 results will be loaded into IDs list
                    for i in range(300, 3000, 100):
                        self.browser.execute_script("arguments[0].scrollTo(0, {})".format(i), scrollresults[0])
                    scrollresults = self.get_elements("search")
                    #time.sleep(1)

                # get job links, (the following are actually the job card objects)
                if self.is_present(self.locator["links"]):
                    links = self.get_elements("links")
                # links = self.browser.find_elements("xpath",
                #     '//div[@data-job-id]'
                # )

                    jobIDs = {} #{Job id: processed_status}
                
                    # children selector is the container of the job cards on the left
                    for link in links:
                            if 'Applied' not in link.text: #checking if applied already
                                if link.text not in self.blacklist: #checking if blacklisted
                                    jobID = link.get_attribute("data-job-id")
                                    if jobID == "search":
                                        log.debug("Job ID not found, search keyword found instead? {}".format(link.text))
                                        continue
                                    else:
                                        jobIDs[jobID] = "To be processed"
                    if len(jobIDs) > 0:
                        self.apply_loop(jobIDs)
                    self.browser, jobs_per_page = self.next_jobs_page(position,
                                                                      location,
                                                                      jobs_per_page, 
                                                                      experience_level=self.experience_level)
                else:
                    self.browser, jobs_per_page = self.next_jobs_page(position,
                                                                      location,
                                                                      jobs_per_page, 
                                                                      experience_level=self.experience_level)


            except Exception as e:
                print(e)
        
        if self.applications_count >= self.max_applications:
            log.info(f"Application limit reached! Successfully submitted {self.applications_count} applications.")
        else:
            log.info(f"Search completed. Total applications submitted: {self.applications_count}")
    def apply_loop(self, jobIDs):
        for jobID in jobIDs:
            if jobIDs[jobID] == "To be processed":
                applied = self.apply_to_job(jobID)
                if applied:
                    log.info(f"Applied to {jobID}")
                else:
                    log.info(f"Failed to apply to {jobID}")
                jobIDs[jobID] == applied

    def parse_salary(self, job_description):
        """
        Parse salary information from job description text.
        Returns (yearly_salary, hourly_salary) or (None, None) if not found.
        """
        # Convert to lowercase for easier matching
        text = job_description.lower()
        
        # Patterns for yearly salary (£60,000, £60000, £60k)
        yearly_patterns = [
            r'£\s*(\d{1,3}(?:,\d{3})*)\s*(?:per\s+year|annually|/year|p\.a\.)',
            r'£\s*(\d{2,3})k\s*(?:per\s+year|annually|/year|p\.a\.)',
            r'(\d{1,3}(?:,\d{3})*)\s*£\s*(?:per\s+year|annually|/year|p\.a\.)',
            r'salary.*?£\s*(\d{1,3}(?:,\d{3})*)',
            r'£\s*(\d{1,3}(?:,\d{3})*)\s*-\s*£\s*(\d{1,3}(?:,\d{3})*)',  # range
        ]
        
        # Patterns for hourly salary (£32/hour, £32 per hour)
        hourly_patterns = [
            r'£\s*(\d{1,3}(?:\.\d{2})?)\s*(?:per\s+hour|/hour|hourly)',
            r'(\d{1,3}(?:\.\d{2})?)\s*£\s*(?:per\s+hour|/hour|hourly)',
        ]
        
        # Check yearly patterns
        for pattern in yearly_patterns:
            matches = re.findall(pattern, text)
            if matches:
                try:
                    if isinstance(matches[0], tuple):  # salary range
                        # Take the lower bound of the range
                        salary_str = matches[0][0]
                    else:
                        salary_str = matches[0]
                    
                    # Handle 'k' notation
                    if 'k' in text and salary_str.isdigit():
                        yearly_salary = int(salary_str) * 1000
                    else:
                        yearly_salary = int(salary_str.replace(',', ''))
                    
                    return yearly_salary, None
                except (ValueError, IndexError):
                    continue
        
        # Check hourly patterns
        for pattern in hourly_patterns:
            matches = re.findall(pattern, text)
            if matches:
                try:
                    hourly_salary = float(matches[0])
                    return None, hourly_salary
                except (ValueError, IndexError):
                    continue
        
        return None, None

    def meets_salary_requirements(self, yearly_salary, hourly_salary):
        """
        Check if the salary meets minimum requirements.
        Returns True if salary meets requirements or if no salary found.
        """
        if yearly_salary is None and hourly_salary is None:
            # No salary found, apply anyway
            return True
        
        if yearly_salary is not None:
            meets_yearly = yearly_salary >= self.min_salary_yearly
            log.info(f"Yearly salary: £{yearly_salary:,} - Meets requirement (>= £{self.min_salary_yearly:,}): {meets_yearly}")
            return meets_yearly
        
        if hourly_salary is not None:
            meets_hourly = hourly_salary >= self.min_salary_hourly
            log.info(f"Hourly salary: £{hourly_salary} - Meets requirement (>= £{self.min_salary_hourly}): {meets_hourly}")
            return meets_hourly
        
        return True

    def apply_to_job(self, jobID):
        # #self.avoid_lock() # annoying

        # get job page
        self.get_job_page(jobID)

        # let page load with human-like delay
        time.sleep(random.uniform(1.5, 3.0))
        
        # Check salary requirements
        job_description = self.browser.page_source
        yearly_salary, hourly_salary = self.parse_salary(job_description)
        
        if not self.meets_salary_requirements(yearly_salary, hourly_salary):
            log.info(f"Skipping job {jobID}: salary below requirements")
            self.write_to_file(False, jobID, self.browser.title, False, "* Salary below requirements")
            return False

        # get easy apply button
        button = self.get_easy_apply_button()


        # word filter to skip positions not wanted
        if button is not False:
            if any(word in self.browser.title for word in blackListTitles):
                log.info('skipping this application, a blacklisted keyword was found in the job position')
                string_easy = "* Contains blacklisted keyword"
                result = False
            else:
                string_easy = "* has Easy Apply Button"
                log.info("Clicking the EASY apply button")
                button.click()
                clicked = True
                time.sleep(random.uniform(1.5, 2.5))
                self.fill_out_fields()
                result = self.send_resume()
                if result is True:
                    string_easy = "*Applied: Sent Resume"
                    self.applications_count += 1
                    log.info(f"Application submitted! Total applications: {self.applications_count}")
                    
                    # Try to connect with recruiter after successful application
                    if self.send_recruiter_invites:
                        time.sleep(random.uniform(2, 4))  # Human-like delay
                        self.try_connect_with_recruiter(jobID)
                elif result == "skipped_experience":
                    string_easy = "*Skipped: Zero experience in required skills"
                    result = False
                else:
                    string_easy = "*Did not apply: Failed to send Resume"
                    result = False
        elif "You applied on" in self.browser.page_source:
            log.info("You have already applied to this position.")
            string_easy = "* Already Applied"
            result = False
        else:
            log.info("The Easy apply button does not exist.")
            string_easy = "* Doesn't have Easy Apply Button"
            result = False


        # position_number: str = str(count_job + jobs_per_page)
        log.info(f"\nPosition {jobID}:\n {self.browser.title} \n {string_easy} \n")

        self.write_to_file(button, jobID, self.browser.title, result)
        return result

    def write_to_file(self, button, jobID, browserTitle, result, reason=None) -> None:
        def re_extract(text, pattern):
            target = re.search(pattern, text)
            if target:
                target = target.group(1)
            return target

        timestamp: str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        attempted: bool = False if button == False else True
        job = re_extract(browserTitle.split(' | ')[0], r"\(?\d?\)?\s?(\w.*)")
        company = re_extract(browserTitle.split(' | ')[1], r"(\w.*)")

        toWrite: list = [timestamp, jobID, job, company, attempted, result]
        with open(self.filename, 'a+') as f:
            writer = csv.writer(f)
            writer.writerow(toWrite)

    def get_job_page(self, jobID):

        job: str = 'https://www.linkedin.com/jobs/view/' + str(jobID)
        self.browser.get(job)
        self.job_page = self.load_page(sleep=0.5)
        return self.job_page

    def get_easy_apply_button(self):
        EasyApplyButton = False
        try:
            buttons = self.get_elements("easy_apply_button")
            # buttons = self.browser.find_elements("xpath",
            #     '//button[contains(@class, "jobs-apply-button")]'
            # )
            for button in buttons:
                if "Easy Apply" in button.text:
                    EasyApplyButton = button
                    self.wait.until(EC.element_to_be_clickable(EasyApplyButton))
                else:
                    log.debug("Easy Apply button not found")
            
        except Exception as e: 
            print("Exception:",e)
            log.debug("Easy Apply button not found")


        return EasyApplyButton

    def fill_out_fields(self):
        fields = self.browser.find_elements(By.CLASS_NAME, "jobs-easy-apply-form-section__grouping")
        for field in fields:

            if "Mobile phone number" in field.text:
                field_input = field.find_element(By.TAG_NAME, "input")
                field_input.clear()
                field_input.send_keys(self.phone_number)


        return


    def get_elements(self, type) -> list:
        elements = []
        element = self.locator[type]
        if self.is_present(element):
            elements = self.browser.find_elements(element[0], element[1])
        return elements

    def is_present(self, locator):
        return len(self.browser.find_elements(locator[0],
                                              locator[1])) > 0

    def send_resume(self) -> bool:
        """
        Handle the application submission process.
        If use_linkedin_resume is True, skips file uploads and uses existing LinkedIn resume.
        If use_linkedin_resume is False, uploads local files from config.
        """
        def is_present(button_locator) -> bool:
            return len(self.browser.find_elements(button_locator[0],
                                                  button_locator[1])) > 0

        try:
            #time.sleep(random.uniform(1.5, 2.5))
            next_locator = (By.CSS_SELECTOR,
                            "button[aria-label='Continue to next step']")
            review_locator = (By.CSS_SELECTOR,
                              "button[aria-label='Review your application']")
            submit_locator = (By.CSS_SELECTOR,
                              "button[aria-label='Submit application']")
            error_locator = (By.CLASS_NAME,"artdeco-inline-feedback__message")
            upload_resume_locator = (By.XPATH, '//span[text()="Upload resume"]')
            upload_cv_locator = (By.XPATH, '//span[text()="Upload cover letter"]')
            # WebElement upload_locator = self.browser.find_element(By.NAME, "file")
            follow_locator = (By.CSS_SELECTOR, "label[for='follow-company-checkbox']")

            submitted = False
            loop = 0
            while loop < 2:
                time.sleep(1)
                # Upload resume - only if use_linkedin_resume is False
                if is_present(upload_resume_locator):
                    if not self.use_linkedin_resume and "Resume" in self.uploads:
                        #upload_locator = self.browser.find_element(By.NAME, "file")
                        try:
                            resume_locator = self.browser.find_element(By.XPATH, "//*[contains(@id, 'jobs-document-upload-file-input-upload-resume')]")
                            resume = self.uploads["Resume"]
                            resume_locator.send_keys(resume)
                            log.info("Uploaded local resume file")
                        except Exception as e:
                            log.error(e)
                            log.error("Resume upload failed")
                            log.debug("Resume: " + str(self.uploads.get("Resume", "None")))
                            log.debug("Resume Locator: " + str(resume_locator))
                    else:
                        log.info("Skipping resume upload - using LinkedIn resume")
                        
                # Upload cover letter if possible - only if use_linkedin_resume is False
                if is_present(upload_cv_locator):
                    if not self.use_linkedin_resume and "Cover Letter" in self.uploads:
                        try:
                            cv = self.uploads["Cover Letter"]
                            cv_locator = self.browser.find_element(By.XPATH, "//*[contains(@id, 'jobs-document-upload-file-input-upload-cover-letter')]")
                            cv_locator.send_keys(cv)
                            log.info("Uploaded local cover letter file")
                        except Exception as e:
                            log.error(f"Cover letter upload failed: {e}")
                    else:
                        log.info("Skipping cover letter upload - using LinkedIn resume")

                    #time.sleep(random.uniform(4.5, 6.5))
                elif len(self.get_elements("follow")) > 0:
                    elements = self.get_elements("follow")
                    for element in elements:
                        button = self.wait.until(EC.element_to_be_clickable(element))
                        button.click()

                if len(self.get_elements("submit")) > 0:
                    elements = self.get_elements("submit")
                    for element in elements:
                        button = self.wait.until(EC.element_to_be_clickable(element))
                        button.click()
                        log.info("Application Submitted")
                        submitted = True
                        break

                elif len(self.get_elements("error")) > 0:
                    elements = self.get_elements("error")
                    if "application was sent" in self.browser.page_source:
                        log.info("Application Submitted")
                        submitted = True
                        break
                    elif len(elements) > 0:
                        # Check if we should skip this job due to experience requirements
                        if self.skip_zero_experience:
                            form_fields = self.get_elements("fields")
                            if self.check_experience_requirements(form_fields):
                                log.info("Skipping job due to zero experience in required skills")
                                return "skipped_experience"
                            
                        while len(elements) > 0:
                            log.info("Please answer the questions, waiting 5 seconds...")
                            time.sleep(5)
                            elements = self.get_elements("error")

                            for element in elements:
                                self.process_questions()

                            if "application was sent" in self.browser.page_source:
                                log.info("Application Submitted")
                                submitted = True
                                break
                            elif is_present(self.locator["easy_apply_button"]):
                                log.info("Skipping application")
                                submitted = False
                                break
                        continue
                        #add explicit wait
                    
                    else:
                        log.info("Application not submitted")
                        time.sleep(2)
                        break
                    # self.process_questions()

                elif len(self.get_elements("next")) > 0:
                    elements = self.get_elements("next")
                    for element in elements:
                        button = self.wait.until(EC.element_to_be_clickable(element))
                        button.click()

                elif len(self.get_elements("review")) > 0:
                    elements = self.get_elements("review")
                    for element in elements:
                        button = self.wait.until(EC.element_to_be_clickable(element))
                        button.click()

                elif len(self.get_elements("follow")) > 0:
                    elements = self.get_elements("follow")
                    for element in elements:
                        button = self.wait.until(EC.element_to_be_clickable(element))
                        button.click()

        except Exception as e:
            log.error(e)
            log.error("cannot apply to this job")
            pass
            #raise (e)

        return submitted
    def process_questions(self):
        time.sleep(1)
        form = self.get_elements("fields") #self.browser.find_elements(By.CLASS_NAME, "jobs-easy-apply-form-section__grouping")
        for field in form:
            question = field.text
            answer = self.ans_question(question.lower())
            #radio button
            if self.is_present(self.locator["radio_select"]):
                try:
                    input = field.find_element(By.CSS_SELECTOR, "input[type='radio'][value={}]".format(answer))
                    input.execute_script("arguments[0].click();", input)
                except Exception as e:
                    log.error(e)
                    continue
            #multi select
            elif self.is_present(self.locator["multi_select"]):
                try:
                    input = field.find_element(self.locator["multi_select"])
                    input.send_keys(answer)
                except Exception as e:
                    log.error(e)
                    continue
            # text box
            elif self.is_present(self.locator["text_select"]):
                try:
                    input = field.find_element(self.locator["text_select"])
                    input.send_keys(answer)
                except Exception as e:
                    log.error(e)
                    continue

            elif self.is_present(self.locator["text_select"]):
               pass

            if "Yes" or "No" in answer: #radio button
                try: #debug this
                    input = form.find_element(By.CSS_SELECTOR, "input[type='radio'][value={}]".format(answer))
                    form.execute_script("arguments[0].click();", input)
                except:
                    pass


            else:
                input = form.find_element(By.CLASS_NAME, "artdeco-text-input--input")
                input.send_keys(answer)

    def ans_question(self, question): #refactor this to an ans.yaml file
        # First check if we have a specific answer in our CSV file
        if question in self.answers:
            answer = self.answers[question]
            log.info(f"Using saved answer for: {question} -> {answer}")
            return answer
        
        # If not found in CSV, use hardcoded logic
        answer = None
        if "how many" in question:
            answer = "1"
        elif "experience" in question:
            answer = "1"
        elif "sponsor" in question:
            answer = "No"
        elif 'do you ' in question:
            answer = "Yes"
        elif "have you " in question:
            answer = "Yes"
        elif "US citizen" in question:
            answer = "Yes"
        elif "are you " in question:
            answer = "Yes"
        elif "salary" in question:
            answer = self.salary
        elif "can you" in question:
            answer = "Yes"
        elif "gender" in question:
            answer = "Male"
        elif "race" in question:
            answer = "Wish not to answer"
        elif "lgbtq" in question:
            answer = "Wish not to answer"
        elif "ethnicity" in question:
            answer = "Wish not to answer"
        elif "nationality" in question:
            answer = "Wish not to answer"
        elif "government" in question:
            answer = "I do not wish to self-identify"
        elif "are you legally" in question:
            answer = "Yes"
        else:
            log.info("Not able to answer question automatically. Please provide answer")
            #open file and document unanswerable questions, appending to it
            answer = "user provided"
            time.sleep(15)

            # df = pd.DataFrame(self.answers, index=[0])
            # df.to_csv(self.qa_file, encoding="utf-8")
        
        log.info("Answering question: " + question + " with answer: " + answer)

        # Append question and answer to the CSV for future reference
        if question not in self.answers:
            self.answers[question] = answer
            # Append a new question-answer pair to the CSV file
            new_data = pd.DataFrame({"Question": [question], "Answer": [answer]})
            new_data.to_csv(self.qa_file, mode='a', header=False, index=False, encoding='utf-8')
            log.info(f"Appended to QA file: '{question}' with answer: '{answer}'.")

        return answer

    def check_experience_requirements(self, form_fields):
        """
        Check if any experience-related questions would be answered with 0.
        Returns True if we should skip this job (has zero experience requirements we can't meet).
        """
        try:
            for field in form_fields:
                question_text = field.text.lower().strip()
                
                # Skip if no question text
                if not question_text:
                    continue
                
                # Check if this is an experience-related question
                experience_keywords = [
                    "how many years", "years of experience", "years of work experience",
                    "experience do you have", "how many years experience"
                ]
                
                is_experience_question = any(keyword in question_text for keyword in experience_keywords)
                
                if is_experience_question:
                    # Get what our answer would be
                    answer = self.ans_question(question_text)
                    
                    # Check if answer is 0 or equivalent
                    if str(answer).strip() in ['0', '0.0', 'None', 'none']:
                        log.info(f"Skipping job: Zero experience required for '{question_text[:100]}...'")
                        return True
                        
            return False
            
        except Exception as e:
            log.error(f"Error checking experience requirements: {e}")
            # If we can't check, don't skip the job
            return False

    def try_connect_with_recruiter(self, jobID):
        """
        Try to identify and connect with the recruiter for a job posting.
        """
        try:
            log.info(f"Looking for recruiter information for job {jobID}")
            
            # Go back to job page to find recruiter info
            self.get_job_page(jobID)
            time.sleep(2)
            
            # Look for recruiter information in various places
            recruiter_info = self.find_recruiter_info()
            
            if recruiter_info:
                recruiter_name, recruiter_url, position_title = recruiter_info
                log.info(f"Found recruiter: {recruiter_name} for position: {position_title}")
                
                # Navigate to recruiter profile and send connection
                success = self.send_connection_invite(recruiter_name, recruiter_url, position_title)
                if success:
                    log.info(f"Successfully sent connection invite to {recruiter_name}")
                    time.sleep(random.uniform(3, 6))  # Delay after connection
                else:
                    log.info(f"Failed to send connection invite to {recruiter_name}")
            else:
                log.info("No recruiter information found for this job")
                
        except Exception as e:
            log.error(f"Error connecting with recruiter: {e}")

    def find_recruiter_info(self):
        """
        Find recruiter information on the job page.
        Returns (name, profile_url, position_title) or None if not found.
        """
        try:
            # Get job title for the message
            position_title = "this position"
            try:
                title_element = self.browser.find_element(By.CSS_SELECTOR, "h1.top-card-layout__title")
                position_title = title_element.text.strip()
            except:
                pass
            
            # Look for recruiter info in various selectors
            recruiter_selectors = [
                "div.job-details-jobs-unified-top-card__primary-description-container a[href*='/in/']",
                "div.jobs-poster a[href*='/in/']", 
                "div.jobs-details__main-content a[href*='/in/']",
                "a[data-control-name='job_details_job_poster_link']",
                "div.job-details-jobs-unified-top-card__content a[href*='/in/']"
            ]
            
            for selector in recruiter_selectors:
                try:
                    recruiter_elements = self.browser.find_elements(By.CSS_SELECTOR, selector)
                    for element in recruiter_elements:
                        recruiter_url = element.get_attribute('href')
                        recruiter_name = element.text.strip()
                        
                        # Validate that this looks like a recruiter link
                        if recruiter_url and '/in/' in recruiter_url and recruiter_name:
                            # Skip company pages
                            if '/company/' not in recruiter_url:
                                log.info(f"Found potential recruiter: {recruiter_name} at {recruiter_url}")
                                return recruiter_name, recruiter_url, position_title
                except Exception as e:
                    log.debug(f"Error with selector {selector}: {e}")
                    continue
            
            return None
            
        except Exception as e:
            log.error(f"Error finding recruiter info: {e}")
            return None

    def send_connection_invite(self, recruiter_name, recruiter_url, position_title):
        """
        Send a connection invite to the recruiter with a personalized message.
        """
        try:
            # Navigate to recruiter profile
            self.browser.get(recruiter_url)
            time.sleep(random.uniform(2, 4))
            
            # Look for Connect button
            connect_button = None
            
            # Try direct Connect button first
            try:
                connect_button = self.browser.find_element(By.XPATH, "//button[contains(text(), 'Connect') or @aria-label='Invite to connect']")
            except:
                pass
            
            # If no direct Connect button, try More dropdown
            if not connect_button:
                try:
                    more_button = self.browser.find_element(By.XPATH, "//button[contains(text(), 'More') or @aria-label='More actions']")
                    more_button.click()
                    time.sleep(1)
                    connect_button = self.browser.find_element(By.XPATH, "//div[@role='menu']//button[contains(text(), 'Connect')]")
                except:
                    pass
            
            if not connect_button:
                log.warning(f"Connect button not found for {recruiter_name}")
                return False
            
            # Click Connect button
            connect_button.click()
            time.sleep(2)
            
            # Look for "Add a note" button and click it
            try:
                add_note_button = self.browser.find_element(By.XPATH, "//button[contains(text(), 'Add a note')]")
                add_note_button.click()
                time.sleep(1)
                
                # Find message text area and enter personalized message
                message_area = self.browser.find_element(By.CSS_SELECTOR, "textarea[name='message']")
                
                # Create personalized message
                message = f"Hi {recruiter_name.split()[0]}. I'm Intizar, a Software Engineer and UK Global Talent Visa holder. I saw your post about a {position_title} opening and believe it's a strong match. I've built software for 250M+ users and would be glad to share more."
                
                # Ensure message is under LinkedIn's character limit (300 chars)
                if len(message) > 299:
                    message = f"Hi {recruiter_name.split()[0]}. I'm Intizar, a Software Engineer and UK Global Talent Visa holder. I saw your {position_title} post and believe it's a strong match. I've built software for 250M+ users."
                
                message_area.clear()
                message_area.send_keys(message)
                time.sleep(1)
                
                # Send the invite
                send_button = self.browser.find_element(By.XPATH, "//button[contains(text(), 'Send') or contains(text(), 'Send invitation')]")
                send_button.click()
                time.sleep(2)
                
                log.info(f"Connection invite sent to {recruiter_name} with message: {message}")
                return True
                
            except Exception as e:
                log.warning(f"Could not add note to connection request: {e}")
                # Try to send without note
                try:
                    send_button = self.browser.find_element(By.XPATH, "//button[contains(text(), 'Send') or contains(text(), 'Send invitation')]")
                    send_button.click()
                    time.sleep(2)
                    log.info(f"Connection invite sent to {recruiter_name} without note")
                    return True
                except:
                    log.error(f"Failed to send connection invite to {recruiter_name}")
                    return False
                    
        except Exception as e:
            log.error(f"Error sending connection invite to {recruiter_name}: {e}")
            return False

    def load_page(self, sleep=1):
        scroll_page = 0
        while scroll_page < 4000:
            self.browser.execute_script("window.scrollTo(0," + str(scroll_page) + " );")
            scroll_page += 500
            time.sleep(sleep)

        if sleep != 1:
            self.browser.execute_script("window.scrollTo(0,0);")
            time.sleep(sleep)

        page = BeautifulSoup(self.browser.page_source, "lxml")
        return page

    def avoid_lock(self) -> None:
        x, _ = pyautogui.position()
        pyautogui.moveTo(x + 200, pyautogui.position().y, duration=1.0)
        pyautogui.moveTo(x, pyautogui.position().y, duration=0.5)
        pyautogui.keyDown('ctrl')
        pyautogui.press('esc')
        pyautogui.keyUp('ctrl')
        time.sleep(0.5)
        pyautogui.press('esc')

    def next_jobs_page(self, position, location, jobs_per_page, experience_level=[]):
        # Construct the experience level part of the URL
        experience_level_str = ",".join(map(str, experience_level)) if experience_level else ""
        experience_level_param = f"&f_E={experience_level_str}" if experience_level_str else ""
        # Add filter for jobs posted in last 7 days (604800 seconds)
        date_filter = "&f_TPR=r604800"
        self.browser.get(
            # URL for jobs page
            "https://www.linkedin.com/jobs/search/?f_LF=f_AL&keywords=" +
            position + location + "&start=" + str(jobs_per_page) + experience_level_param + date_filter)
        #self.avoid_lock()
        log.info("Loading next job page?")
        self.load_page()
        return (self.browser, jobs_per_page)

    # def finish_apply(self) -> None:
    #     self.browser.close()


if __name__ == '__main__':

    with open("config.yaml", 'r') as stream:
        try:
            parameters = yaml.safe_load(stream)
        except yaml.YAMLError as exc:
            raise exc

    assert len(parameters['positions']) > 0
    assert len(parameters['locations']) > 0
    assert parameters['username'] is not None
    assert parameters['password'] is not None
    assert parameters['phone_number'] is not None


    if 'uploads' in parameters.keys() and type(parameters['uploads']) == list:
        raise Exception("uploads read from the config file appear to be in list format" +
                        " while should be dict. Try removing '-' from line containing" +
                        " filename & path")

    log.info({k: parameters[k] for k in parameters.keys() if k not in ['username', 'password']})

    output_filename: list = [f for f in parameters.get('output_filename', ['output.csv']) if f is not None]
    output_filename: list = output_filename[0] if len(output_filename) > 0 else 'output.csv'
    blacklist = parameters.get('blacklist', [])
    blackListTitles = parameters.get('blackListTitles', [])

    uploads = {} if parameters.get('uploads', {}) is None else parameters.get('uploads', {})
    for key in uploads.keys():
        assert uploads[key] is not None

    locations: list = [l for l in parameters['locations'] if l is not None]
    positions: list = [p for p in parameters['positions'] if p is not None]

    bot = EasyApplyBot(parameters['username'],
                       parameters['password'],
                       parameters['phone_number'],
                       parameters['salary'],
                       parameters['rate'], 
                       uploads=uploads,
                       filename=output_filename,
                       blacklist=blacklist,
                       blackListTitles=blackListTitles,
                       experience_level=parameters.get('experience_level', []),
                       max_applications=parameters.get('max_applications', 50),
                       min_salary_yearly=parameters.get('min_salary_yearly', 60000),
                       min_salary_hourly=parameters.get('min_salary_hourly', 32),
                       send_recruiter_invites=parameters.get('send_recruiter_invites', True),
                       skip_zero_experience=parameters.get('skip_zero_experience', True),
                       use_linkedin_resume=parameters.get('use_linkedin_resume', True)
                       )
    bot.start_apply(positions, locations)


