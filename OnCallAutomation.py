import os
import pandas as pd
from simple_salesforce import Salesforce
import requests
import opsgenie_sdk
import re
import json
import datetime
from datetime import datetime
import traceback
import logging

# Construct an absolute path to the config.json file containing login info
script_dir = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.join(script_dir, 'config.json')

# Use the absolute path to load the config
with open(config_path, 'r') as config_file:
    config = json.load(config_file)['sfops']

now = datetime.now()

opsgenie_api_url = config['opsgenie_api_url']
opsgenie_api_url_notes = config['opsgenie_api_url_notes']
opsgenie_api_key = config['opsgenie_api_key']
sf_username = config['sf_username']
sf_password = config['sf_password']
sf_security_token = config['sf_token']
api_client = ''

class CaseCreation:

    def __init__(self, opsgenie_api_url, opsgenie_api_url_notes, opsgenie_api_key, sf_username, sf_password, sf_security_token):
        self.opsgenie_api_url = opsgenie_api_url
        self.opsgenie_api_url_notes = opsgenie_api_url_notes
        self.opsgenie_api_key = opsgenie_api_key
        self.conf = opsgenie_sdk.configuration.Configuration()
        self.conf.api_key['Authorization'] = opsgenie_api_key
        self.api_client = opsgenie_sdk.api_client.ApiClient(configuration=self.conf)
        self.alert_api = opsgenie_sdk.AlertApi(api_client=self.api_client)
        self.sf_username = sf_username
        self.sf_password = sf_password
        self.sf_security_token = sf_security_token


    def get_alerts(self):
        headers = {
                  'Authorization': 'GenieKey {}'.format(self.opsgenie_api_key),
                  'Content-Type': 'application/json'
            }
        response = requests.get(opsgenie_api_url, headers=headers)
        alerts = response.json()['data']

        for alert in alerts:
            print(alert['id'])
            if alert['status'] == 'open':
                tag = alert['tags']
                if tag: # if there's a tag
                    existingCase = re.search("^[0-9]", tag[0])
                    if existingCase: # and if there is already a SF case
                        print("no case created because a case already exists")
                    else:
                        print("create case")
                        recipient = newCaseCreation.get_alert_recipients(alert['id'])
                        newCaseCreation.createCase(alert, recipient)
                else:
                    print("create case")
                    recipient = newCaseCreation.get_alert_recipients(alert['id'])
                    newCaseCreation.createCase(alert, recipient)
            else:#if case is closed
                tag = alert['tags']
                if tag: # if there's a tag check to see if there's a SF case
                    existingCase = re.search("^[0-9]", tag[0])
                    if existingCase: # and if there is a SF case
                        print("close sf case")
                        newCaseCreation.close_case(tag[0]) #close the SF case

    def get_alert_recipients(self, alert_id):
        list_recipients_response = self.alert_api.list_recipients(identifier=alert_id)
        return list_recipients_response.data[0].user.username

    def createCase(self, alert, recipient):
            sf = Salesforce(username = self.sf_username, password = self.sf_password, security_token = self.sf_security_token)
            query = "SELECT Id FROM User WHERE Email = '" + recipient + "' LIMIT 100"
            result = sf.query_all(query)
            records = result['records']
            df = pd.DataFrame(records)
            ownerId = df['Id'].head(1).to_string(index=False)

            data ={
                  "Subject" : alert['message'],
                  "Priority" : "high",
                  "OwnerId" : ownerId,
                  "Description": alert['message']
                }

            case = sf.Case.create(data, headers = {"Sforce-Auto-Assign": "False" })    # Create a case assigned to on-call engineer
            newCaseCreation.get_case_num(case,alert)

    def get_case_num(self, case,alert):
        case_id = case.get("id")
        sf = Salesforce(username = self.sf_username, password = self.sf_password, security_token = self.sf_security_token)
        query = "SELECT FIELDS(STANDARD) FROM Case WHERE Id = '" + case_id + "' LIMIT 100"
        result = sf.query_all(query)

            # Convert the query results to a Pandas DataFrame
        records = result['records']
        df = pd.DataFrame(records)

        caseId = df['Id'].head(1).to_string(index=False)
        newCaseCreation.add_salesforce_link(caseId, alert)
        newCaseCreation.add_documentation_link(alert)

        caseNumber = df['CaseNumber'].head(1).to_string(index=False)
        newCaseCreation.add_tag(caseNumber, alert)

    def add_salesforce_link(self, caseId, alert):
        identifier = alert['id']
        note = 'Case: https://collective.lightning.force.com/lightning/r/Case/'+ caseId +'/view'
        body = opsgenie_sdk.AddNoteToAlertPayload(user='API', note=note, source='python sdk')
        self.alert_api.add_note(identifier=identifier, add_note_to_alert_payload=body)
       
    def add_documentation_link(self, alert):
        alertTypes = {'alertTypeMA':re.search("MA_", alert['message'])}
        note = 'Documentation: ' + 'https://confluence.pointclickcare.com/confluence/display/IE/On-Call+Alert+Guide'
       
        if alertTypes.get('alertTypeMA'):
            note = 'Documentation: ' + 'https://confluence.pointclickcare.com/confluence/display/IE/Mass+ENS+Related+Alerts'

        identifier = alert['id']
        body = opsgenie_sdk.AddNoteToAlertPayload(user='API', note=note, source='python sdk')
        self.alert_api.add_note(identifier=identifier, add_note_to_alert_payload=body)    

    def add_tag(self, caseNumber, alert):
        identifier = alert['id']
        body = opsgenie_sdk.AddTagsToAlertPayload(tags=[caseNumber])
        self.alert_api.add_tags(add_tags_to_alert_payload=body, identifier=identifier)
       
    def ack_alert(self, alertId):
        identifier = alertId
        body = opsgenie_sdk.AcknowledgeAlertPayload(user='API', source='python sdk')
        self.alert_api.acknowledge_alert(identifier=identifier, acknowledge_alert_payload=body)
       
    def close_case(self, caseNumber):
        sf = Salesforce(username = self.sf_username, password = self.sf_password, security_token = self.sf_security_token)
        query = "SELECT FIELDS(STANDARD) FROM Case WHERE CaseNumber = '" + caseNumber + "' LIMIT 100"
        result = sf.query_all(query)

            # Convert the query results to a Pandas DataFrame
        records = result['records']
        df = pd.DataFrame(records)
        df['IsDeleted'] = False
        try:
            caseId = df['Id'].head(1).to_string(index=False)
        except Exception as e:
            logging.error(traceback.format_exc())
       
        data ={
        "Origin" : "API",
        "Type" : "Other",
        "Status" : "Closed - Resolved"
       
        }
        try:
            sf.Case.update(caseId, data)  
        except Exception as e:
            logging.error(traceback.format_exc())
       
         

newCaseCreation = CaseCreation(opsgenie_api_url, opsgenie_api_url_notes, opsgenie_api_key, sf_username, sf_password, sf_security_token)
newCaseCreation.get_alerts()