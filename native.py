import os,requests,sys,re
import json,urllib.request
import logging,time,uuid
import pandas as pd
from datetime import datetime,timedelta
import functools,csv

print = functools.partial(print, flush=True)    # forces flush=True for all print() calls

try:
  tenant_id = os.getenv('ARM_TENANT_ID')
  if tenant_id is None:
    raise ValueError("Environment variable 'ARM_TENANT_ID' is not set.")
except ValueError as e:
  print(f"Error: {e}")
  sys.exit()

try:
  client_id=os.getenv('ARM_CLIENT_ID')
  if client_id is None:
    raise ValueError("Environment variable 'ARM_CLIENT_ID' is not set.")
except ValueError as e:
  print(f"Error: {e}")
  sys.exit()

try:
  client_secret = os.getenv('ARM_CLIENT_SECRET')
  if client_secret is None:
    raise ValueError("Environment variable 'ARM_CLIENT_SECRET' is not set.")
except ValueError as e:
  print(f"Error: {e}")
  sys.exit()

def get_token(resource):
    data_body = (
        f"grant_type=client_credentials&client_id={client_id}"
        f"&client_secret={client_secret}&resource=https%3A%2F%2F{resource}%2F"
    )

    bindata = data_body.encode("utf-8")
    url = f'https://login.microsoftonline.com/{tenant_id}/oauth2/token'
    req = urllib.request.Request(url=url, data=bindata, method='POST')

    try:
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode())
            return result.get('access_token')
    except (urllib.error.HTTPError, urllib.error.URLError) as e:
        print(f"Token Error {e.code if hasattr(e, 'code') else e.reason}")
    except ConnectionResetError as e:
      print("Token Connection was reset by the peer: ", e)
      return None
    except Exception as e:
      print("Token An unexpected error occurred: ", e)
      return None
    return None


def fetch_resource_graph_results(query,token):
    if not token:
        token = get_token('management.azure.com')
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
    resource_graph_url = "https://management.azure.com/providers/Microsoft.ResourceGraph/resources?api-version=2021-03-01"

    all_results = []
    skip_token = None
    top = 990
    skip = 0

    while True:
        # Prepare the request payload
        payload = {
            "query": query,
#            "managementGroups": [ "abcde" ],
            "options": {
                "resultFormat": "objectArray"
            }
        }

        payload["$skip"] = skip
        payload["$top"] = top

        if skip_token:
            payload["options"]["$skipToken"] = skip_token

        headers = {
        'Authorization': f"Bearer {token}",
        'Content-Type': 'application/json',
        }
        data=[]
        try:
          response = requests.post(resource_graph_url, headers=headers, data=json.dumps(payload))
          data = response.json()
        except:
          pass
        if 'data' in data:
          all_results.extend(data['data'])
        if '$skipToken' in data:
          skip_token=data['$skipToken']
          print(len(all_results),"roles retrieved, hold on...")
          time.sleep(0.5)
        elif 'resultTruncated' in data:
          if data['resultTruncated'] == "true":
            skip += top
            time.sleep(0.5)
          else:
            break
        else:
          break
    return all_results,token

def microsoft_graph_query(url, token=None):
    if not token:
        token = get_token('graph.microsoft.com')

    headers = {'Authorization': f'Bearer {token}'}
    req = urllib.request.Request(url=url, method='GET', headers=headers)

    try:
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode())
            return result, token,response.code
    except (urllib.error.HTTPError, urllib.error.URLError) as e:
        if hasattr(e, 'code'):
          if int(e.code)!=404:
            print(f"MS Graph Error {e.code if hasattr(e, 'code') else e.reason}",url)
        return None,token,e.code if hasattr(e, 'code') else e.reason
    except ConnectionResetError as e:
      print("MS Graph Connection was reset by the peer: ", e)
      return None,token,None
    except Exception as e:
      print("MS Graph An unexpected error occurred: ", e)
      return None,token,None
    return None, token,None

def get_groups_of(principalId,principalType,token):
  if principalType=='ServicePrincipal':
    url='https://graph.microsoft.com/v1.0/servicePrincipals/'+principalId+'/transitiveMemberOf'
  elif principalType=='User':
    url='https://graph.microsoft.com/v1.0/users/'+principalId+'/transitiveMemberOf'
  else:
    return None,token
  rez,token, code=microsoft_graph_query(url,token)
  return rez,token
