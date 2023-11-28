#!/usr/bin/python3

import csv
import os,requests,sys,re
import json,urllib.request
import logging,time,uuid
from datetime import datetime,timedelta


tenant_id=os.getenv('tenantid')
client_id=os.getenv('clientid')
client_secret=os.getenv('clientsecret')
account=os.getenv('minimizer')
ground=os.getenv('ingest_ground')
partition=os.getenv('ingest_partition')

def get_rows(account,table,PK):
  SAS=os.getenv(f"{account}_sas")
  print(account,table,PK)
  url=f"https://{account}.table.core.windows.net/{table}()?$filter=PartitionKey%20eq%20%27"+PK+"%27&"+SAS
  headers={'Accept': 'application/json;odata=nometadata'}
  req=urllib.request.Request(url=url, data=None, headers=headers)
  data=[]
  try:
    with urllib.request.urlopen(req) as response:
      data = json.loads(str(response.read(),'utf-8'))
      if 'value' in data:
        return data['value']
  except urllib.error.HTTPError as e:
    logging.info("code %s",str(e.code))
  except urllib.error.URLError as e:
    if hasattr(e, 'reason'):
      logging.info("reason %s",str(e.reason))
    elif hasattr(e, 'code'):
      logging.info("code2 %s",str(e.code))
  return None

rz=get_rows(account,ground,partition)
json_inputs=[]
for aZ in rz:
  it={}
  it['name']=aZ['Name']
  it['gwar']=aZ['GWAR']
  it['swar']=aZ['SWAR']
  if aZ['GWResolution']>9999: 
    it['gwresolution']=0.0
  else:
    it['gwresolution']=aZ['GWResolution']/8.0
  if aZ['GAResolution']>9999: 
    it['garesolution']=0.0
  else:
    it['garesolution']=aZ['GAResolution']/8.0
  if aZ['SSResolution']>9999:
    it['ssresolution']=0.0
  else:
    it['ssresolution']=aZ['SSResolution']/8.0
  if aZ['SWResolution']>9999:
    it['swresolution']=0.0
  else:
    it['swresolution']=aZ['SWResolution']/8.0
  if aZ['SAResolution']>9999:
    it['saresolution']=0.0
  else:
    it['saresolution']=aZ['SAResolution']/8.0
  payload=json.loads(aZ['Payload'])
  it['rps']=payload['Wrps']+payload['Arps']
  json_inputs.append(it)
unique_rps = set()
data = []
for json_str in json_inputs:
    records = json_str['rps'].split(";")
    data.append(json_str)
    for rps_value in records:
      if len(rps_value)>0:
        unique_rps.add(rps_value)

# Sort unique_rps for consistent column ordering
unique_rps = sorted(unique_rps)

# Prepare CSV file headers
headers = ['Name', 'GWAR', 'SWAR','GWResolution','GAResolution', 'SSResolution','SWResolution','SAResolution' ] + list(unique_rps)

# Create and write to CSV file
with open(f"{partition}_output.csv", 'w', newline='') as file:
    writer = csv.DictWriter(file, fieldnames=headers)
    writer.writeheader()
    for record in data:
        row = {'Name': record['name'], 'GWAR': record['gwar'], 'SWAR': record['swar'], 'GWResolution': record['gwresolution'],'GAResolution': record['garesolution'], 'SSResolution': record['ssresolution'], 'SWResolution': record['swresolution'], 'SAResolution': record['saresolution'] }
        # Set one-hot encoding for rps
        for rps in unique_rps:
            row[rps] = 1 if rps in record['rps'] else 0
        writer.writerow(row)
print("")
print(f"CSV file '{partition}_output.csv' created with {len(headers)} columns.")

