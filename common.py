import os,requests,sys,re
import json,urllib.request,socket,random
import logging,time,uuid,gzip
from datetime import datetime,timedelta
from z3 import *
import functools
print = functools.partial(print, flush=True) 

tenant_id=os.getenv('tenantid')
client_id=os.getenv('clientid')
client_secret=os.getenv('clientsecret')
account=os.getenv('minimizer')
wid = os.getenv(f"{account}_wid")
build_groundsource = os.getenv(f"{account}_build_ground")
run_groundsource = os.getenv(f"{account}_run_ground")
build_goldensource = os.getenv(f"{account}_build_golden")
run_goldensource = os.getenv(f"{account}_run_golden")
orphans = os.getenv(f"{account}_orphans")
unused = os.getenv(f"{account}_unused")
run_partition=os.getenv('run_partition')

RG_PATTERN0=re.compile(os.getenv("RG_PATTERN0"))
RG_PATTERN1=re.compile(os.getenv("RG_PATTERN1"))

logsRetention=90 # Log Analytics retention, in days. MUST be greater than 0.

membership={}
warpermdict={}
cosinecache={}
dstamp=datetime.now().strftime("%y%m%d")

silhouette={
        'superadmin': {
            '0': 0,     # none
            '1': 950,   # tenant
            '2': 900,   # mgmt group
            '3': 850,   # subscription
            '4': 800,   # RG
            '6': 750,   # resource
            '8': 700,   # subresource
            },
         'write/delete': {
            '0': 0,
            '1': 600,
            '2': 500,
            '3': 400,
            '4': 300,
            '6': 200,
            '8': 100,
            },
         'action_scaleddown': {
            '0': 0,
            '1': 45,
            '2': 40,
            '3': 35,
            '4': 30,
            '6': 20,
            '8': 10
         },
         'action': {
            '0': 0,
            '1': 90,
            '2': 80,
            '3': 70,
            '4': 60,
            '6': 40,
            '8': 20
         },
         'read_scaleddown': {
            '0': 0,
            '1': 4,
            '2': 4,
            '3': 3,
            '4': 2,
            '6': 1,
            '8': 1
         },
         'read': {
            '0': 0,
            '1': 9,
            '2': 8,
            '3': 7,
            '4': 6,
            '6': 4,
            '8': 2
         }
        }

permSort=DeclareSort('permission')

def addPerm(prm):
  gprm="_"+prm
  globals()[gprm]=None
  gprm=Const(prm,permSort)
  return gprm

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

def upload_blob(account,pk,principalId,json_obj):
  SAS=os.getenv(f"{account}_sas")
  url=f"https://{account}.blob.core.windows.net/"+pk+'/'+principalId+'.json.gz?'+SAS
  try:
    json_str = json.dumps(json_obj)
    bindata = gzip.compress(json_str.encode('utf-8'))
  except Exception as e:
    logging.info("Cannot convert JSON to bytes")
    print(f"Cannot convert JSON to bytes, error: {e}")
    return False
  req=urllib.request.Request(url=url, data=bindata, method='PUT')
  req.add_header('X-Ms-Blob-Type', 'BlockBlob')
  req.add_header('Content-Encoding', 'gzip')
  try:
    with urllib.request.urlopen(req,timeout=10) as response:
      logging.info("response %s",str(response.code))
      print("response",str(response.code))
      return True
  except urllib.error.HTTPError as e:
    logging.info("code %s",str(e.code))
    print("code",str(e.code))
  except urllib.error.URLError as e:
    if hasattr(e, 'reason'):
      logging.info("reason %s",str(e.reason))
      print("reason",str(e.reason))
    elif hasattr(e, 'code'):
      logging.info("code2 %s",str(e.code))
      print("code2",str(e.code))
  return False

def download_blob(account,pk,principalId):
  max_retries=1
  SAS=os.getenv(f"{account}_sas")
  url=f"https://{account}.blob.core.windows.net/"+pk+'/'+principalId+'.json.gz?'+SAS
  for attempt in range(0,max_retries+1):
    try:
      req=urllib.request.Request(url=url, method='GET')
      with urllib.request.urlopen(req,timeout=7) as response:
          compressed_data = response.read()
      decompressed_data = gzip.decompress(compressed_data)
      json_str = decompressed_data.decode('utf-8')
      json_obj = json.loads(json_str)
      return json_obj
    except urllib.error.HTTPError as e:
      logging.info("code %s",str(e.code))
    except urllib.error.URLError as e:
      if hasattr(e, 'reason'):
        if isinstance(e.reason, socket.timeout):
          print(f"Download attempt {attempt +1} timed out:", e)
          if attempt < max_retries:
            print("Retrying...")
            time.sleep(1)
          else:
            return None
        logging.info("reason %s",str(e.reason))
      elif hasattr(e, 'code'):
        logging.info("code2 %s",str(e.code))
    except ConnectionResetError as e:
      print("Row Connection was reset by the peer: ", e)
      return None
    except Exception as e:
      print(f"Error: {str(e)}")
      return None

def get_row(account,table,PK,RK):
  SAS=os.getenv(f"{account}_sas")
  url=f"https://{account}.table.core.windows.net/{table}()?$filter=PartitionKey%20eq%20%27"+PK+"%27%20and%20RowKey%20eq%20%27"+RK+"%27&"+SAS
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
  except ConnectionResetError as e:
        print("Row Connection was reset by the peer: ", e)
        return None
  except Exception as e:
        print("Row An unexpected error occurred: ", e)
        return None
  return None

def get_all_rows(account, table):
    SAS = os.getenv(f"{account}_sas")
    base_url = f"https://{account}.table.core.windows.net/{table}()?{SAS}"

    def fetch_data(url):
        headers={}
        headers['Accept']='application/json;odata=nometadata'
        req = urllib.request.Request(url=url, data=None, headers=headers)
        try:
            with urllib.request.urlopen(req) as response:
                zheaders={}
                for key, value in response.headers.items():
                  if 'x-ms-continuation-next' in key.lower():
                    zheaders[key]=value
                return json.loads(str(response.read(), 'utf-8')),zheaders
        except urllib.error.HTTPError as e:
            logging.info("code %s", str(e.code))
        except urllib.error.URLError as e:
            if hasattr(e, 'reason'):
                logging.info("reason %s", str(e.reason))
            elif hasattr(e, 'code'):
                logging.info("code2 %s", str(e.code))
        except ConnectionResetError as e:
            print("All Rows Connection was reset by the peer: ", e)
        except Exception as e:
            print("All Rows An unexpected error occurred: ", e)
        return None,None

    all_data = []
    next_partition_key = None
    next_row_key = None

    while True:
        url = base_url
        if next_partition_key and next_row_key:
            url += f"&NextPartitionKey={next_partition_key}&NextRowKey={next_row_key}"
        data,zheaders = fetch_data(url)
        zdata = []
        if data and 'value' in data:
            for aD in data['value']:
              if 'Name' in aD and len(aD['Name'])<=100:
                zdata.append(aD)
            all_data.extend(zdata)
            if 'x-ms-continuation-NextPartitionKey' in zheaders:
              next_partition_key = zheaders['x-ms-continuation-NextPartitionKey']
            else:
              next_partition_key=None
            if 'x-ms-continuation-NextRowKey' in zheaders:
              next_row_key = zheaders['x-ms-continuation-NextRowKey']
            else:
              next_row_key=None
            if not next_partition_key or not next_row_key:
                break
        else:
            break

    return all_data

def store_row(account,table,PK,RK,payload):
  SAS=os.getenv(f"{account}_sas")
  dbody={"PartitionKey": PK,"RowKey":RK,"Payload":payload}
  bindata=json.dumps(dbody).encode("utf-8")
  url=f"https://{account}.table.core.windows.net/{table}(PartitionKey=%27"+PK+"%27,RowKey=%27"+RK+"%27)?"+SAS
  req=urllib.request.Request(url=url, data=bindata,method='PUT')
  req.add_header('Accept','application/json;odata=nometadata')
  req.add_header('Content-Type','application/json')
  try:
    with urllib.request.urlopen(req) as response:
      logging.info("response %s",str(response.code))
      return True
  except urllib.error.HTTPError as e:
    logging.info("code %s",str(e.code))
    print("Store row code",str(e.code))
  except urllib.error.URLError as e:
    if hasattr(e, 'reason'):
      logging.info("reason %s",str(e.reason))
      print("Store row reason",str(e.reason))
    elif hasattr(e, 'code'):
      logging.info("code2 %s",str(e.code))
      print("Store row code2",str(e.code))
  except ConnectionResetError as e:
      print("Store row Connection was reset by the peer: ", e)
      return False 
  except Exception as e:
      print("Store row An unexpected error occurred: ", e)
      return False 
  return False

def store_row5u(account,table,PK,RK,display,enabled,created,ptype,payload):
  SAS=os.getenv(f"{account}_sas")
  if display is None:
    dname=''
  else:
    dname=str(display)
  dbody={"PartitionKey": PK,"RowKey":RK,"Name": dname, "accountEnabled": enabled, "createdDateTime": created, "servicePrincipalType": ptype, "Payload":payload}
  bindata=json.dumps(dbody).encode("utf-8")
  url=f"https://{account}.table.core.windows.net/{table}(PartitionKey=%27"+PK+"%27,RowKey=%27"+RK+"%27)?"+SAS
  req=urllib.request.Request(url=url, data=bindata,method='PUT')
  req.add_header('Accept','application/json;odata=nometadata')
  req.add_header('Content-Type','application/json')
  try:
    with urllib.request.urlopen(req) as response:
      logging.info("response %s",str(response.code))
      return True
  except urllib.error.HTTPError as e:
    logging.info("code %s",str(e.code))
    print("Store Row5u code",str(e.code))
  except urllib.error.URLError as e:
    if hasattr(e, 'reason'):
      logging.info("reason %s",str(e.reason))
      print("Store Row5u reason",str(e.reason))
    elif hasattr(e, 'code'):
      logging.info("code2 %s",str(e.code))
      print("Store Row5u code2",str(e.code))
  except ConnectionResetError as e:
      print("Store Row5u Connection was reset by the peer: ", e)
      return False
  except Exception as e:
      print("Store Row5u An unexpected error occurred: ", e)
      return False
  return False

def store_row5(account,table,PK,RK,display,war,Sresolution,Wresolution,Aresolution,da,payload):
  SAS=os.getenv(f"{account}_sas")
  if display is None:
    dname=''
  else:
    dname=str(display)
  dbody={"PartitionKey": PK,"RowKey":RK,"Name": dname, "WAR": war, "Sresolution": Sresolution,"Wresolution": Wresolution,"Aresolution": Aresolution, "DA": da,"Payload":payload}
  bindata=json.dumps(dbody).encode("utf-8")
  url=f"https://{account}.table.core.windows.net/{table}(PartitionKey=%27"+PK+"%27,RowKey=%27"+RK+"%27)?"+SAS
  req=urllib.request.Request(url=url, data=bindata,method='PUT')
  req.add_header('Accept','application/json;odata=nometadata')
  req.add_header('Content-Type','application/json')
  try:
    with urllib.request.urlopen(req) as response:
      logging.info("response %s",str(response.code))
      return True
  except urllib.error.HTTPError as e:
    logging.info("code %s",str(e.code))
    print("Store Row5 code",str(e.code))
  except urllib.error.URLError as e:
    if hasattr(e, 'reason'):
      logging.info("reason %s",str(e.reason))
      print("Store Row5 reason",str(e.reason))
    elif hasattr(e, 'code'):
      logging.info("code2 %s",str(e.code))
      print("Store Row5 code2",str(e.code))
  except ConnectionResetError as e:
      print("Store Row5 Connection was reset by the peer: ", e)
      return False
  except Exception as e:
      print("Store Row5 An unexpected error occurred: ", e)
      return False
  return False

def store_row7(account,table,PK,RK,display,swar,gwar,sda,gda,sSresolution,sWresolution,sAresolution,gSresolution,gWresolution,gAresolution):
  SAS=os.getenv(f"{account}_sas")
  if display is None:
    dname=''
  else:
    dname=str(display)
  dbody={"PartitionKey": PK,"RowKey":RK,"Name": dname, "SWAR": swar, "GWAR": gwar, "SDA": sda , "GDA": gda, "SSResolution": sSresolution,"SWResolution": sWresolution,"SAResolution": sAresolution,"GSResolution": gSresolution,"GWResolution": gWresolution,"GAResolution": gAresolution}
  bindata=json.dumps(dbody).encode("utf-8")
  url=f"https://{account}.table.core.windows.net/{table}(PartitionKey=%27"+PK+"%27,RowKey=%27"+RK+"%27)?"+SAS
  req=urllib.request.Request(url=url, data=bindata,method='PUT')
  req.add_header('Accept','application/json;odata=nometadata')
  req.add_header('Content-Type','application/json')
  try:
    with urllib.request.urlopen(req) as response:
      logging.info("response %s",str(response.code))
      return True
  except urllib.error.HTTPError as e:
    logging.info("code %s",str(e.code))
    print("Store row7 code",str(e.code))
  except urllib.error.URLError as e:
    if hasattr(e, 'reason'):
      logging.info("reason %s",str(e.reason))
      print("Store row7 reason",str(e.reason))
    elif hasattr(e, 'code'):
      logging.info("code2 %s",str(e.code))
      print("Store row7 code2",str(e.code))
  except ConnectionResetError as e:
      print("Store row7 Connection was reset by the peer: ", e)
      return False
  except Exception as e:
      print("Store row7 An unexpected error occurred: ", e)
      return False
  return False

def store_row8(account,table,PK,RK,display,gwar,swar,gSresolution,gWresolution,gAresolution,sSresolution,sWresolution,sAresolution,gda,sda,payload):
  SAS=os.getenv(f"{account}_sas")
  if display is None:
    dname=''
  else:
    dname=str(display)
  dbody={"PartitionKey": PK,"RowKey":RK,"Name": dname, "SWAR": swar, "GWAR": gwar, "SSResolution": sSresolution, "SWResolution": sWresolution, "SAResolution": sAresolution,  "GSResolution": gSresolution, "GWResolution": gWresolution, "GAResolution": gAresolution,"SDA": sda, "GDA": gda, "Payload":payload}
  bindata=json.dumps(dbody).encode("utf-8")
  url=f"https://{account}.table.core.windows.net/{table}(PartitionKey=%27"+PK+"%27,RowKey=%27"+RK+"%27)?"+SAS
  req=urllib.request.Request(url=url, data=bindata,method='PUT')
  req.add_header('Accept','application/json;odata=nometadata')
  req.add_header('Content-Type','application/json')
  try:
    with urllib.request.urlopen(req) as response:
      logging.info("response %s",str(response.code))
      return True
  except urllib.error.HTTPError as e:
    logging.info("code %s",str(e.code))
    print("Store row8 code",str(e.code))
  except urllib.error.URLError as e:
    if hasattr(e, 'reason'):
      logging.info("reason %s",str(e.reason))
      print("Store row8 reason",str(e.reason))
    elif hasattr(e, 'code'):
      logging.info("code2 %s",str(e.code))
      print("Store row8 code2",str(e.code))
  except ConnectionResetError as e:
      print("Store row8 Connection was reset by the peer: ", e)
      return False
  except Exception as e:
      print("Store row8 An unexpected error occurred: ", e)
      return False
  return False

def new_partition():
  return str(uuid.uuid4())

def get_groups_of(principalId,principalType,token):
  if principalType=='ServicePrincipal':
    url='https://graph.microsoft.com/v1.0/servicePrincipals/'+principalId+'/transitiveMemberOf'
  elif principalType=='User':
    url='https://graph.microsoft.com/v1.0/users/'+principalId+'/transitiveMemberOf'
  else:
    return None,token
  rez,token, code=microsoft_graph_query(url,token)
  return rez,token

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

def fetch_logs_by_id(workspace_id,principalId,dFrom,dTo,token):
    max_retries=2
    if not token:
        token = get_token('api.loganalytics.io')
    headers = {
    'Content-Type': 'application/json',
    'Authorization': f'Bearer {token}'
    }
    query='''
AzureActivity
| where isnotempty(Authorization_d.action)
| where TimeGenerated<datetime("
'''
    query=query[:-1]+dTo
    query=query+'''")
| where TimeGenerated>=datetime("
'''
    query=query[:-1]+dFrom
    query=query+'''")
| where Caller=="
'''
    query=query[:-1]+principalId
    query=query+'''"
| where not(ActivityStatusValue in ("Failure","Failed","Success"))
| project TimeGenerated,Authorization_d.action,Authorization_d.evidence.role,Authorization_d.scope,Authorization_d.evidence.roleDefinitionId,Authorization_d.evidence.roleAssignmentId,Authorization_d.evidence.roleAssignmentScope,ActivityStatusValue
'''
    api_url = f'https://api.loganalytics.io/v1/workspaces/{workspace_id}/query' 
    post_data = json.dumps({'query': query}).encode('utf-8')
    for attempt in range(0,max_retries):
      try:
        req = urllib.request.Request(api_url, post_data, headers)
        response = urllib.request.urlopen(req)
        response_data = json.loads(response.read())
        return response_data['tables'][0]['rows'],token
      except urllib.error.HTTPError as e:
        print(f"Fetch logs HTTP error occurred: {e.code} - {e.reason}")
        return None,token
      except urllib.error.URLError as e:
        print(f"Fetch logs URL error occurred: {e.reason}")
        return None,token
      except Exception as e:
        print(f"Fetch logs An unexpected error occurred: {e}")
        return None,token
      if attempt < max_retries+1:
        time.sleep(10)

def build_ground_truth(wid,principalId,display,sFrom,sTo,token,verbose):
  token=None
  actionXscope={}
  row=get_row(account,run_goldensource,run_partition,principalId)
  if row is None or len(row)==0:
    if verbose:
      print("empty row")
    return None,False,None,None,None,token 
  gsource={}
  pld=json.loads(row[0]['Payload'])
  gsource['war']=pld['war']
  gsource['da']=pld['da']
  gsource['Wrps']=pld['Wrps']
  gsource['Arps']=pld['Arps']
  gsource['Sresolution']=pld['Sresolution']
  gsource['Wresolution']=pld['Wresolution']
  gsource['Aresolution']=pld['Aresolution']
  groundroles={}
  goldenroles={}
  cached=False
  payload=download_blob(account,run_partition,principalId)
  if payload is None:
    print(principalId,"payload MISS")
    payload,token=fetch_logs_by_id(wid,principalId,sFrom,sTo,token)
  else:
    cached=True
    print(principalId,"payload HIT")
  if payload is None:
    if verbose:
      print(" no activity")
    return None,False,None,None,None,token 
  if not cached:
    print("now uploading")
    upload_blob(account,run_partition,principalId,payload)
    time.sleep(0.4)
  if verbose:
    print(display,principalId,"logs:",len(payload))
  super_classes={}
  super_res=set([])
  write_delete_classes={}
  write_delete_providers=set({})
  write_res=set([])
  action_classes={}
  action_providers=set({})
  action_res=set([])
  read_classes={}
  read_providers=set({})
  read_res=set([])
  define_classes={}
  assign_classes={}
  i=-1
  for aP in payload:
    i+=1
    roleId=aP[4]
    roleId=roleId[:-12]+'-'+roleId[20:]
    roleId=roleId[:-17]+'-'+roleId[16:]
    roleId=roleId[:-22]+'-'+roleId[12:]
    roleId=roleId[:-27]+'-'+roleId[8:]
    if roleId not in groundroles:
      groundroles[roleId]={}
      scope=aP[3]
      resource,resolution=extract_azure_resource_details(scope)
      groundroles[roleId]['resolution']=resolution
      groundroles[roleId]['scope']=scope
      groundroles[roleId]['name']=aP[2]
      groundroles[roleId]['actions']=set([])
    action=aP[1].lower()
    war=classify_war_permission(action,8,False)
    wcl=None
    if war[0]=='write/delete':
      wcl='W'
    elif war[0]=='action':
      wcl='A'
    elif war[0]=='read':
      wcl='R'
    if wcl is not None:
      ss,srg=subRGscope(aP[3])
      if wcl not in actionXscope:
        actionXscope[wcl]={}
      if ss not in actionXscope[wcl]:
        actionXscope[wcl][ss]={}
      if srg not in actionXscope[wcl][ss]:
        actionXscope[wcl][ss][srg]=[]
      if action not in actionXscope[wcl][ss][srg]:
        actionXscope[wcl][ss][srg].append(action)
    groundroles[roleId]['actions'].add(action)
  zperms=set()
  for aGR in groundroles:
    classes,rps,stars = partition_permissions(list(groundroles[aGR]['actions']),groundroles[aGR]['resolution'],zperms)
    super_res.add(groundroles[aGR]['resolution'])
    super_classes.update(classes["superadmin"])

    write_res.add(groundroles[aGR]['resolution'])
    write_delete_classes.update(classes["write/delete"])
    write_delete_providers.update(rps["write/delete"])

    action_res.add(groundroles[aGR]['resolution'])
    action_classes.update(classes["action"])
    action_providers.update(rps["action"])

    read_res.add(groundroles[aGR]['resolution'])
    read_classes.update(classes["read"])
    read_providers.update(rps["read"])

    define_classes.update(classes["define"])
    assign_classes.update(classes["assign"])

  war=''
  da=''
  Sresolution=9999999999
  Wresolution=9999999999
  Aresolution=9999999999
  if len(super_classes)>0:
    war='S'
    Sresolution=min(super_res)
  elif len(write_delete_classes)>0:
    war='W'
    Wresolution=min(write_res)
  elif len(action_classes)>0:
    war='A'
    Aresolution=min(action_res)
  elif len(read_classes)>0:
    war='R'
  if len(super_classes)==0:
    if len(define_classes)>0:
      da+='D'
    if len(assign_classes)>0:
      da+='G'
  ground={}
  ground['Wrps']=''
  ground['Arps']=''
  if len(write_delete_classes)>0:
    srps=''
    if '*' in write_delete_providers:
      ground['Wrps']='W_*;'
    else:
      for rp in write_delete_providers:
        ground['Wrps']+='W_'+str(rp)+';'
  else:
    ground['Wrps']=";"
  if len(action_classes)>0:
    srps=''
    if '*' in action_providers:
      ground['Arps']='A_*;'
    else:
      for rp in action_providers:
        ground['Arps']+='A_'+str(rp)+';'
  else:
    ground['Arps']=";"
  isUsed=False
  if len(war)>0 or len(da)>0:
    isUsed=True
    if not verbose:
      store_row8(account,build_groundsource,build_partition,principalId,display,war,gsource['war'],Sresolution,Wresolution,Aresolution,gsource['Sresolution'],gsource['Wresolution'],gsource['Aresolution'],da,gsource['da'],json.dumps(ground))
  return zperms,isUsed,gsource,ground,actionXscope,token

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
        try:
          response = requests.post(resource_graph_url, headers=headers, data=json.dumps(payload))
          data = response.json()
        except:
          pass
        if 'data' in data:
          all_results.extend(data['data'])
        if '$skipToken' in data:
          skip_token=data['$skipToken']
          time.sleep(0.15)
        elif 'resultTruncated' in data:
          if data['resultTruncated'] == "true":
            skip += top
            time.sleep(0.15)
          else:
            break
        else:
          break
    return all_results,token

def extract_azure_resource_details(s):
    pattern = r'/subscriptions/(?P<subscription>[^/]+)/resourcegroups/(?P<rg>[^/]+)/providers/(?P<provider>[^/]+)/(?P<type>[^/]+)/(?P<name>[^/]+)/(?P<subtype>[^/]+)/(?P<subname>[^/]+)'
    match = re.search(pattern, s.lower())
    if match:
      return (None,None,match.group('subscription'),match.group('rg'),match.group('provider'), match.group('type'), match.group('name'),match.group('subtype'), match.group('subname')),8
    pattern = r'/subscriptions/(?P<subscription>[^/]+)/resourcegroups/(?P<rg>[^/]+)/providers/(?P<provider>[^/]+)/(?P<type>[^/]+)/(?P<name>[^/]+)'
    match = re.search(pattern, s.lower())
    if match:
      return (None,None,match.group('subscription'),match.group('rg'),match.group('provider'), match.group('type'), match.group('name'),None,None),6
    pattern = r'/subscriptions/(?P<subscription>[^/]+)/resourcegroups/(?P<rg>[^/]+)'
    match = re.search(pattern, s.lower())
    if match:
      return (None,None,match.group('subscription'),match.group('rg'),None , None, None,None,None),4
    pattern = r'/subscriptions/(?P<subscription>[^/]+)'
    match = re.search(pattern, s.lower())
    if match:
      return (None,None,match.group('subscription'),None ,None , None, None,None,None),3
    pattern = r'/providers/microsoft.management/managementgroups/(?P<mgmtGroup>)'
    match = re.search(pattern, s.lower())
    if match: 
      return (None,match.group('mgmtGroup'),None,None,None,None,None,None,None),2
    if s=='/':
      return ('/',None,None,None,None,None,None,None,None),1
    return None,None

def subRGscope(s):
   pattern = r'/subscriptions/(?P<subscription>[^/]+)/resourcegroups/(?P<rg>[^/]+)'
   match = re.search(pattern, s.lower())
   if match:
     return match.group('subscription'),match.group('rg')
   else:
     return '',''

class DisjointSet:
    def __init__(self, permissions):
        self.parent = {}
        self.rank = {}
        for permission in permissions:
            self.parent[permission] = permission
            self.rank[permission] = 0

    def find(self, permission):
        if self.parent[permission] != permission:
            self.parent[permission] = self.find(self.parent[permission])
        return self.parent[permission]

    def union(self, permission1, permission2):
        root1 = self.find(permission1)
        root2 = self.find(permission2)
        if root1 != root2:
            if self.rank[root1] > self.rank[root2]:
                self.parent[root2] = root1
            else:
                self.parent[root1] = root2
                if self.rank[root1] == self.rank[root2]:
                    self.rank[root2] += 1

def classify_war_permission(permission,resolution,verbose):
    global warpermdict
    lowperms = permission.lower()
    segments = lowperms.split("/")

    if segments[0]!='*':
      rp=segments[0]
    else:
      rp=None

    if "microsoft.insights/" in lowperms or "microsoft.support/" in lowperms or "microsoft.resourcehealth/" in lowperms or "microsoft.alertsmanagement/" in lowperms or "microsoft.consumption/" in lowperms or "microsoft.costmanagement/" in lowperms:
        if verbose:
          wpd=permission+":R:"+str(resolution)
          if wpd not in warpermdict:
            warpermdict[wpd]=0
#            print(permission,"R",resolution)
        return "read",segments[0]

    if permission == "*" or permission == "/*":
      if resolution>=8:
        if verbose:
          wpd=permission+":A:"+str(resolution)
          if wpd not in warpermdict:
            warpermdict[wpd]=0
#            print(permission,"A",resolution)
        return "action",segments[0]
      elif resolution>=6:
        if verbose:
          wpd=permission+":W:"+str(resolution)
          if wpd not in warpermdict:
            warpermdict[wpd]=0
#            print(permission,"W",resolution)
        return "write/delete",segments[0]
      else:
        if verbose:
          wpd=permission+":S:"+str(resolution)
          if wpd not in warpermdict:
            warpermdict[wpd]=0
#            print(permission,"S",resolution)
        return "superadmin",segments[0]
    
    if "microsoft.authorization/" in lowperms:
      if "microsoft.authorization/denyassignments" in lowperms:
        return "none",segments[0]
      if "microsoft.authorization/elevateaccess" in lowperms:
        return "none",segments[0]
      if "microsoft.authorization/classicadministrators" in lowperms:
        return "none",segments[0]
      if "microsoft.authorization/roleassignments" in lowperms:
        return "none",segments[0]
      if "microsoft.authorization/roledefinitions" in lowperms:
        return "none",segments[0]
      if "microsoft.authorization/roleeligibilityschedule" in lowperms:
        return "none",segments[0]
      if "microsoft.authorization/rolemanagementpolic" in lowperms:
        return "none",segments[0]


    if segments[-1:][0]=="*":
        if verbose:
            wpd=permission+":S:"+str(resolution)
            if wpd not in warpermdict:
              warpermdict[wpd]=0
#              print(permission,"S",resolution)
        return "superadmin",rp

    if "write" in segments[-1:][0].lower() or "delete" in segments[-1:][0].lower():
        if verbose:
          wpd=permission+":W:"+str(resolution)
          if wpd not in warpermdict:
            warpermdict[wpd]=0
#            print(permission,"W",resolution)
        return "write/delete",rp
    elif "action" in segments[-1:][0].lower():
        if verbose:
          wpd=permission+":A:"+str(resolution)
          if wpd not in warpermdict:
            warpermdict[wpd]=0
#            print(permission,"A",resolution)
        return "action",rp
    elif "read" in segments[-1:][0].lower():
        if verbose:
          wpd=permission+":R:"+str(resolution)
          if wpd not in warpermdict:
            warpermdict[wpd]=0
#            print(permission,"R",resolution)
        return "read",rp
    if verbose:
      wpd=permissions+":U:"+str(resolution)
      if wpd not in warpermdict:
        warpermdict[wpd]=0
#        print(permission,"U",resolution)
    return "unknown",segments[0]

def classify_da_permission(permission):
    lowperms = permission.lower()
    segments = lowperms.split("/")

    assigner=False
    designer=False

    if "microsoft.authorization/" not in lowperms:
        return "none"

    if permission == "*" or permission == "/*":
        return "superadmin"

    if "microsoft.authorization/roleassignments" in lowperms:
        assigner=True

    if "microsoft.authorization/roledefinitions" in lowperms:
        designer=True

    if "microsoft.authorization/diagnosticsettings" in lowperms:
        return "none"

    if "microsoft.authorization/locks" in lowperms:
        return "none"

    if "microsoft.authorization/polic" in lowperms:
        return "none"

    if "microsoft.authorization/provideroperations" in lowperms:
        return "none"

    if any("write" in segment or "delete" in segment for segment in segments):
        if designer and not(assigner):
          return "define"
        if assigner and not(designer):
          return "assign"
        else:
          return "superadmin"

    if segments[-1:][0]=="*":
        if designer and not(assigner):
          return "define"
        if assigner and not(designer):
          return "assign"
        else:
          return "superadmin"

    if any("action" in segment for segment in segments):
        if designer and not(assigner):
          return "define"
        if assigner and not(designer):
          return "assign"
        else:
          return "superadmin"

    if any("read" in segment for segment in segments):
        return "read"

    return "unknown"


def partition_permissions(permissions,resolution,zperms):
    war_sets = {
        "superadmin": DisjointSet(permissions),
        "read": DisjointSet(permissions),
        "write/delete": DisjointSet(permissions),
        "action": DisjointSet(permissions),
        "none": DisjointSet(permissions),
        "unknown": DisjointSet(permissions)
    }
    war_classes = {
        "read": {},
        "superadmin": {},
        "write/delete": {},
        "action": {},
        "none": {},
        "unknown": {}
    }
    da_sets = {
        "superadmin": DisjointSet(permissions),
        "define": DisjointSet(permissions),
        "assign": DisjointSet(permissions),
        "unknown": DisjointSet(permissions),
        "none": DisjointSet(permissions),
        "read": DisjointSet(permissions)
    }
    da_classes = {
        "read": {},
        "define": {},
        "superadmin": {},
        "assign": {},
        "none": {},
        "unknown": {}
    }

    classes = {
        "read": {},
        "superadmin": {}
    }

    war_rps= {
        "read": set({}),
        "superadmin": set({}),
        "write/delete": set({}),
        "action": set({}),
        "none": set({}),
        "unknown": set({})
    }

    for i in range(len(permissions)):
        for j in range(i + 1, len(permissions)):
            if permissions[i].split("/")[0] == permissions[j].split("/")[0]:
                war_sets[classify_war_permission(permissions[i],resolution,False)[0]].union(permissions[i], permissions[j])
                da_sets[classify_da_permission(permissions[i])].union(permissions[i], permissions[j])
    stars=set()
    for permission in permissions:
        cwp,rp=classify_war_permission(permission,resolution,True)
        zitem=cwp+":"+str(resolution)+":"+permission.lower()
        zperms.add(zitem)
        if '*' in zitem and cwp!='read':
          stars.add(zitem)
        war_root = war_sets[cwp].find(permission)
        war_classes[cwp].setdefault(war_root, set()).add(permission)
        if rp:
          war_rps[cwp].add(rp)
        else:
          war_rps[cwp].add("*")
        cdp=classify_da_permission(permission)
        da_root = da_sets[cdp].find(permission)
        da_classes[cdp].setdefault(da_root, set()).add(permission)

    classes["superadmin"]=war_classes["superadmin"].copy()
    classes["superadmin"].update(da_classes["superadmin"])
    classes["read"]=war_classes["read"].copy()
    classes["read"].update(da_classes["read"])
    classes["write/delete"]=war_classes["write/delete"]
    classes["action"]=war_classes["action"]
    classes["define"]=da_classes["define"]
    classes["assign"]=da_classes["assign"]
    return classes,war_rps,stars

def entity_exists(principal_id, principal_type,token):
    base_url = "https://graph.microsoft.com/v1.0"
    if principal_type=="User":
      url = f"{base_url}/users/{principal_id}"
    elif principal_type=="Group": 
      url = f"{base_url}/groups/{principal_id}"
    elif principal_type=="ServicePrincipal": 
      url = f"{base_url}/servicePrincipals/{principal_id}"
    result, token, code = microsoft_graph_query(url, token)
    if result:
        display_name = result.get('displayName', '')
        display_name += "("+principal_id+")"
        return code,token, display_name,True,result
    return code,token, None,False,None

def fetch_assignments_by_id(principalId,verbose,group,token):
  starRoles={}
  query='''
authorizationresources
    | where type == "microsoft.authorization/roleassignments"
    | where tostring(properties.principalId) == "
'''
  query=query[:-1]+principalId
  query=query+'''"
    | extend roleId = tostring(properties.roleDefinitionId)
    | join kind = inner (authorizationresources
    | where ['type'] has "roledefinitions"
    | distinct tostring(properties.roleName), ['id'],tostring(properties.permissions[0].actions),tostring(properties.permissions[0].dataactions),tostring(properties.permissions[0].notdataactions)) on $left.roleId == $right.['id']
    | extend combinedRole = pack('role',tostring(properties_roleName),'scope',tostring(properties.scope),'actions',properties_permissions_0_actions,'dataactions',properties_permissions_0_actions,'notdataactions',properties_permissions_0_notdataactions,'ra',['id'],'rd', tostring(roleId) )
    | summarize make_set(combinedRole) by tostring(properties.principalType)
    | order by ['properties_principalType'] asc
'''
  results,Rtoken = fetch_resource_graph_results(query=query,token=None)
  if len(results)==0:
    aR={}
    aR['set_combinedRole']=[]
    code,token,display,exists,entity=entity_exists(principalId,"User",token=None)
    aR['properties_principalType']="User"
    if not exists:
      code,token,display,exists,entity=entity_exists(principalId,"ServicePrincipal",token=None)
      aR['properties_principalType']="ServicePrincipal"
    if not exists:
      code,token,display,exists,entity=entity_exists(principalId,"Group",token=None)
      aR['properties_principalType']="Group"
    if not exists:
      print(principalId,"doesnt exist")
      orpartition=principalId[:2]
      store_row(account,orphans,orpartition,principalId,'')
      return None,None,None,None,None,None,None,None,None,None,None,None,None,None,None,None,None,None,None,token
  else:
    aR=results[0]
    code,token,display,exists,entity=entity_exists(principalId,aR['properties_principalType'],token=None)
    if exists==False and code and int(code)==404:
      print(principalId,aR['properties_principalType'],"doesnt exist")
      orpartition=principalId[:2]
      store_row(account,orphans,orpartition,principalId,'')
      return None,None,None,None,None,None,None,None,None,None,None,None,None,None,None,None,None,None,None,token
  combined=aR['set_combinedRole']
  if display:
    d=display
  else:
    d=principalId
  super_classes={}
  super_res=set([])
  write_delete_classes={}
  write_delete_providers=set({})
  write_res=set([])
  action_classes={}
  action_providers=set({})
  action_res=set([])
  read_classes={}
  read_providers=set({})
  read_res=set([])
  define_classes={}
  assign_classes={}
  resourceProviders=set({})
  resolution=9999999999
  g0=None
  war=''
  permset=set()
  dactions=set()
  notdactions=set()
  if aR['properties_principalType'] in ['User','ServicePrincipal']:
    g0,token=get_groups_of(principalId,aR['properties_principalType'],token)
  if g0 and 'value' in g0:
    groups=set([])
    for ag in g0['value']:
      groups.add(ag['id'])
    grcnt=0
    for gr in groups:
      pset,cbr,war,da,sc,sr,wc,wr,ac,ar,rc,rr,dc,gc,rrw,rra,rrr,dac,notdac,token=fetch_assignments_by_id(gr,verbose=verbose,group=True,token=token)   
      if war is None:
        continue
      if "displayName" in ag:
        gdn=ag['displayName']
      else:
        gdn=''
#      print("  group ",gr,gdn)
      if dac:
        dactions.update(dac)
      if notdac:
        notdactions.update(notdac)
      permset.update(pset)
      combined+=cbr 
      if sc is not None and len(sc)>0:
        print("group __+__",sc)
      super_classes.update(sc)
      super_res.update(sr)
      write_delete_classes.update(wc)
      write_delete_providers.update(rrw)
      write_res.update(wr)
      action_classes.update(ac)
      action_providers.update(rra)
      action_res.update(ar)
      read_classes.update(rc)
      read_providers.update(rrr)
      read_res.update(rr)
      if 'D' in da:
        define_classes.update(dc)
      if 'A' in da:
        assign_classes.update(gc)
      grcnt+=1
  buf=d
  for aC in aR['set_combinedRole']:
    actions=json.loads(aC['actions'])
    scope=aC['scope']
    resource,resolution=extract_azure_resource_details(scope)
    if len(aC['dataactions'])>0:
      dal=json.loads(aC['dataactions'])
      zdal=[]
      for ada in dal:
#        if ada!="*":
        zdal.append(ada)
      if len(zdal)>0:
        da=str(resource)+':'+str(scope)+':'+str(zdal)
        dactions.add(da)
    if len(aC['notdataactions'])>0:
      nda=str(resource)+':'+str(scope)+':'+aC['notdataactions']
      notdactions.add(nda)
    if not scope:
      print("UNKNOWN SCOPE:",scope)
      sys.exit()
    classes,rps,stars = partition_permissions(actions,resolution,permset)
    for astar in stars:
      if astar not in starRoles:
        starRoles[astar]=set([])
      starRoles[astar].add(aC['rd'])
    if len(classes["superadmin"])>0:
      super_res.add(resolution)
      super_classes.update(classes["superadmin"])
    if len(classes["write/delete"])>0:
      write_res.add(resolution)
      write_delete_classes.update(classes["write/delete"])
      write_delete_providers.update(rps["write/delete"])
    if len(classes["action"])>0:
      action_res.add(resolution)
      action_classes.update(classes["action"])
      action_providers.update(rps["action"])
    if len(classes["read"])>0:
      read_res.add(resolution)
      read_classes.update(classes["read"])
      read_providers.update(rps["read"])
    define_classes.update(classes["define"])
    assign_classes.update(classes["assign"])
  war=''
  da=''
  jbuf={}
  jbuf['Wrps']=''
  jbuf['Arps']=''
  if len(super_classes)>0:
    war='S'
  elif len(write_delete_classes)>0:
    war='W'
  elif len(action_classes)>0:
    war='A' 
  elif len(read_classes)>0:
    war='R'
  else:
    war='N'
  if len(write_delete_classes)>0:
    srps=''
    if '*' in write_delete_providers:
      jbuf['Wrps']='W_*;'
    else:
      for rp in write_delete_providers:
        jbuf['Wrps']+='W_'+str(rp)+';'
  else:
    jbuf['Wrps']=';'
  if len(action_classes)>0:
    srps=''
    if '*' in action_providers:
      jbuf['Arps']='A_*;'
    else:
      for rp in action_providers:
        jbuf['Arps']+='A_'+str(rp)+';'
  else:
    jbuf['Arps']=';'
  if len(super_classes)==0:
    if len(define_classes)>0:
      da+='D'
    if len(assign_classes)>0:
      da+='G'
  jbuf['war']=war
  jbuf['da']=da
  jbuf['name']=d
  jbuf['Sresolution']=9999999999
  jbuf['Wresolution']=9999999999
  jbuf['Aresolution']=9999999999
  if len(super_res)>0:
    jbuf['Sresolution']=min(super_res)
  if len(write_res)>0:
    jbuf['Wresolution']=min(write_res)
  if len(action_res)>0:
    jbuf['Aresolution']=min(action_res)
  if group:
    print("(group)")
  if not verbose and not group:
    print("storing")
    store_row5(account,build_goldensource,build_partition,principalId,d,war,jbuf['Sresolution'],jbuf['Wresolution'],jbuf['Aresolution'],da,json.dumps(jbuf))
  return permset,combined,war,da,super_classes,super_res,write_delete_classes,write_res,action_classes,action_res,read_classes,read_res,define_classes,assign_classes,write_delete_providers,action_providers,read_providers,list(dactions),list(notdactions),token

def investigate_principalId(pk,principalId,verbose):
  golden_permset,combined,war,da,super_classes,super_res,write_delete_classes,write_res,action_classes,action_res,read_classes,read_res,define_classes,assign_classes,write_delete_providers,action_providers,read_providers,dactions,notdactions,token=fetch_assignments_by_id(principalId,verbose=verbose,group=False,token=None)
  if war is None:
    return None,None,None,None,None,None,None,None,None,None
  ground_permset,isUsed,gsource,ground,axs,token=build_ground_truth(wid,principalId,"",timeBack,timeNow,token=None,verbose=verbose)
  return golden_permset,ground_permset,axs,da,super_res,write_res,action_res,read_res,dactions,notdactions

def build_silhouette(pk,render):
  import csv
  with open(f"clusters_{pk}.json",'r') as cz:
    czc=json.load(cz)
  cls=len(czc)
  with open("html_scores_pre.skeleton", 'r') as ff:
    pre=ff.read()
    ff.close()
  with open("html_scores_post.skeleton", 'r') as ff:
    post=ff.read()
    ff.close()
  buf='Cluster ID;SPN counts;Current silhouette;Desired silhouette;Score\n'
  with open(f"silhouette_{run_partition}_{dstamp}.csv", 'w', newline='') as file:
    writer = csv.DictWriter(file, fieldnames=["Cluster ID","SPN counts","Current silhouette","Desired silhouette","Effort"])
    writer.writeheader()
    for cl in czc:
      print(f"reviewing cluster {cl}/{cls}...")
      c,o,d=generate_condensate(pk,str(cl),None,True,False)
      row={'Cluster ID': 'CLUSTER'+str(cl), 'SPN counts': c, 'Current silhouette': o, 'Desired silhouette': d, 'Effort': o-d}
      writer.writerow(row)
      buf+=str(cl)+';'+str(c)+';'+str(o)+';'+str(d)+';'+str(o-d)+'\n' 
  with open(f"silhouette_{run_partition}_{dstamp}.html", 'w') as ff:
    ff.write(pre)
    ff.write(buf)
    ff.write(post)

def generate_condensate(pk,cluster,strat,verbose,debug,merged):
  global cosinecache
  outer_sil={
          'write/delete': 0,
          'action': 0,
          'none': 0,
          'unknown': 0,
          'read':0  
          }
  inner_sil={
          'write/delete': 0,
          'action': 0,
          'none': 0,
          'unknown': 0,
          'read': 0 
          }
  desired_sil={
          'write/delete': 0,
          'action': 0,
          'none': 0,
          'unknown': 0,
          'read':0
          }

  # to be run after ml-ingest.py and ml.py
  golden_counts={}
  ground_counts={}
  if merged:
    cfile=f"merged_clusters_{pk}.json"
  else:
    cfile=f"clusters_{pk}.json"
  with open(cfile,'r') as cz:
    czc=json.load(cz)
  scluster=str(cluster)
  cntid=0
  counts=len(czc[scluster])
  axsdict={}
  sxadict={}
  p2n={}
  das=[]
  dactions=set()
  notdactions=set()
  random.shuffle(czc[scluster])
  for record in czc[scluster]:
    name,pid=record['Name'].split('(')
    pid=pid[:-1]
    gop,grp,axs,da,sres,wres,ares,rres,dac,notdac=investigate_principalId(pk,pid,verbose)
    if gop is None:
      continue
    if dac:
      dactions.update(dac)
    if notdac:
      notdactions.update(notdac)
    if sres and len(sres)>0:
      msr=max(sres)
    else:
      msr=0
    if wres and len(wres)>0:
      mwr=max(wres)
    else:
      mwr=0
    if ares and len(ares)>0:
      mar=max(ares)
    else:
      mar=0
    if rres and len(rres)>0:
      mrr=max(rres)
    else:
      mrr=0
    maxres=max(msr,mwr,mar,mrr)
    #print(record,"SRES",sres,"WRES",wres,"ARES",ares,"RRES",rres,"MAXRES",maxres)
    if len(da)>0:
      das.append(pid)
    axsdict[pid]=axs
    p2n[pid]=name
    for aw in axs:
      if aw not in sxadict:
        sxadict[aw]={}
      for ax in axs[aw]:
        if ax not in sxadict[aw]:
          sxadict[aw][ax]={}
        for ar in axs[aw][ax]:
          if ar not in sxadict[aw][ax]:
            sxadict[aw][ax][ar]={}
          if pid not in sxadict[aw][ax][ar]:
            sxadict[aw][ax][ar][pid]=[]
          for asc in axs[aw][ax][ar]:
            if asc not in sxadict[aw][ax][ar][pid]:
              sxadict[aw][ax][ar][pid].append(asc)
    if gop is None:
      continue
    if grp is None:
      continue
    cntid+=1
    for g in gop:
      if g not in golden_counts:
        golden_counts[g]=1
      else:
        golden_counts[g]+=1
    for g in grp:
      if g not in ground_counts:
        ground_counts[g]=1
      else:
        ground_counts[g]+=1
  if cntid==0:  # empty cluster... weird!
    return
  if maxres>=6:
    print("WARNING. Some resources have direct role assignments. Currently, Silhouette only supports role assignments to resource containers (MGs,subscriptions,RGs). Resource role assignments must be added manually to role definitions")
  if len(dactions)>0 or len(notdactions)>0:
    print("WARNING. Some cluster members have data plane actions or notActions. They are not managed by Silhouette and must be added manually to cluster/SPN role definition.")
    for aa in dactions:
       print("  dataActions:",aa)
    for na in notdactions:
       print("  notDataActions:",na)
  if len(das)>0:
    print("WARNING: the following principals have IAM role definitions or role assignments. These are not currently supported by Silhouette and must be added manually to cluster custom roles:")
    for d in das:
      print(p2n[d],d)
  if verbose:
    print("\nCurrent permissions from Azure Entra (golden source):")
  someSuperAdmin=False
  for g in golden_counts:
    cl,res,pr=g.split(':')
    if verbose:
      print("  ",str(g))
    if cl=='superadmin':
      someSuperAdmin=True
      if silhouette[cl][str(res)]> outer_sil['write/delete']:
        outer_sil['write/delete']=silhouette[cl][str(res)]
    elif cl=='write/delete':
      if silhouette[cl][str(res)]> outer_sil['write/delete']:
        outer_sil['write/delete']=silhouette[cl][str(res)]
  if someSuperAdmin:
    print("WARNING: some SPNs in this cluster are superadmins. Superadmins have implicit IAM role definitions and role assignments, these are not currently supported by Silhouette so they must be added manually to SPN superadmins custom roles.")
  for g in golden_counts:
    cl,res,pr=g.split(':')
    #scaled=outer_sil['write/delete']>=700
    scaled=True
    if cl=='action' or cl=='read':
      if scaled:
        if silhouette[cl+'_scaleddown'][str(res)]>outer_sil[cl]:
          outer_sil[cl]=silhouette[cl+'_scaleddown'][str(res)]
      else:
        if silhouette[cl][str(res)]>outer_sil[cl]:
          outer_sil[cl]=silhouette[cl][str(res)]
  outerscore=outer_sil['write/delete']+outer_sil['action']+outer_sil['read']
  if debug:
    with open(f"{cluster}_ground_permissions.json","w") as cgp:
      cgp.write("[")
      cgp.write(json.dumps(axsdict,indent=2))
      cgp.write(",\n")
      cgp.write(json.dumps(sxadict,indent=2))
      cgp.write("]\n")
    print("Current silhouette= ",outerscore) 
    print("")
    print("Ground permissions from Azure activity logs, excluding read actions and data actions (ground truth):")
  for g in ground_counts:
    cl,res,pr=g.split(':')
    if verbose:
      print(g,cl,res)
    maxSubs={
            'W': 0,
            'A': 0,
            'R': 0}
    maxRGs={
            'W': 0,
            'A': 0,
            'R': 0}
    strategy={
            'W': '',
            'A': '',
            'R': ''}
    ards={}
    parent_sets={}
  if True:
    for nm in axsdict:
      ards[nm]={
              'MG': [],
              'SUB': [],
              'RG0': [],
              'RG1': [],
              'RG2': [],
              'RG3': [],
              'RG4': []
              }
      parent_sets[nm]={
              'MG': [],
              'SUB': [],
              'RG0': [],
              'RG1': [],
              'RG2': [],
              'RG3': [],
              'RG4': []
      }
      for aw in axsdict[nm]:
        subcnt=len(axsdict[nm][aw])
        if subcnt>maxSubs[aw]:
          maxSubs[aw]=subcnt
        for ss in axsdict[nm][aw]:
          rgcnt=len(axsdict[nm][aw][ss])
          if rgcnt>maxRGs[aw]:
            maxRGs[aw]=rgcnt
    for aw in ['W','A','R']:
      if maxSubs[aw]>=20:
        strategy[aw]='MG'
      else:
        if maxRGs[aw]==1:
          strategy[aw]='SUB'
        elif maxRGs[aw]>1:
          strategy[aw]='RG'
        else:
          strategy[aw]=None
      if strategy[aw] is not None:
        if strat is None:
#          strategy[aw]='RG'
          pass
        else:
          strategy[aw]=strat
    print("STRATEGY",strategy)
    print("max Subs:",maxSubs,"max RGs:",maxRGs)
    ard={}
    ard['Actions']={
              'RG0': set(),
              'RG1': set(),
              'RG2': set(),
              'RG3': set(),
              'RG4': set(),
              'SUB': set(),
              'MG': set()
    }
    desired={
              'RG0': set(),
              'RG1': set(),
              'RG2': set(),
              'RG3': set(),
              'RG4': set(),
              'SUB': set(),
              'MG': set()
    }
    for aw in ['W','A','R']:
      if strategy[aw] is None:
        continue
      if strategy[aw]=='RG':
        for ss in sxadict[aw]: 
          for rg in sxadict[aw][ss]:
            print("NEW RG set",rg," ",end='')
            if rg not in cosinecache:
              if re.match(RG_PATTERN0,rg):
                cosinecache[rg]=0
                print(rg,"matches", RG_PATTERN0)
              elif re.match(RG_PATTERN1,rg):
                cosinecache[rg]=1
                print(rg,"matches", RG_PATTERN1)
              else:
                cosinecache[rg]=2
                print(rg,"matches no pattern")
            rgcat='RG'+str(cosinecache[rg])
            print("CAT",rgcat)
            ard['Actions'][rgcat]=set()
            for nm in sxadict[aw][ss][rg]:
              for an in sxadict[aw][ss][rg]:
                if an==nm:
                  for ac in sxadict[aw][ss][rg][an]:
                    # Local R actions are absorbed by local A actions
                    if aw=='R' and strategy['A'] is not None and strategy['A']=='RG' and ss in sxadict['A'] and rg in sxadict['A'][ss] and an in sxadict['A'][ss][rg]:
                      pass
                    # Local R and A actions are absorbed by local W actions
                    elif aw!='W' and strategy['W'] is not None and strategy['W']=='RG' and ss in sxadict['W'] and rg in sxadict['W'][ss] and an in sxadict['W'][ss][rg]:
                      pass
                    else:
                      # Local W actions cannot be absorbed by an upper authority. So we add them. 
                      ard['Actions'][rgcat].add(ac)
                      print("  Case W: rg",rg,"cat",rgcat,"add",ac)
#                      else:
                        # remaining A and W actions are not local. We ignore them (they will be handled by their SUB or MG strategy).
#                        pass
                  # Local W absorbs local A actions (so RG actions)
                  if aw=='W' and strategy['A'] is not None and strategy['A']=='RG' and ss in sxadict['A'] and rg in sxadict['A'][ss] and an in sxadict['A'][ss][rg]:
                    for ac in sxadict['A'][ss][rg][an]:
                      print("  Case W>A: rg",rg,"cat",rgcat,"add",ac)
                      ard['Actions'][rgcat].add(ac)
                  # Local W and local A absorb local R actions
                  if aw!='R' and strategy['R'] is not None and strategy['R']=='RG' and ss in sxadict['R'] and rg in sxadict['R'][ss] and an in sxadict['R'][ss][rg]:
                    for ac in sxadict['R'][ss][rg][an]:
                      print("  Case W|A>R: rg",rg,"cat",rgcat,"add",ac)
                      ard['Actions'][rgcat].add(ac)
                      if cluster=="20":
                        print("artificially adding perm microsoft.network/routetables/write")
            if len(ard['Actions']['RG0'])>0:
              ards[nm]['RG0'].append(sorted(list(ard['Actions']['RG0'])))
              ard['Actions']['RG0'].add('R::'+rg)
              print("Parent set addition for rg0",rg,ard['Actions']['RG0'])
              parent_sets[nm]['RG0'].append(ard['Actions']['RG0'])
            if len(ard['Actions']['RG1'])>0:
              ards[nm]['RG1'].append(sorted(list(ard['Actions']['RG1'])))
              ard['Actions']['RG1'].add('R::'+rg)
              print("Parent set addition for rg1",rg,ard['Actions']['RG1'])
              parent_sets[nm]['RG1'].append(ard['Actions']['RG1'])
            if len(ard['Actions']['RG2'])>0:
              ards[nm]['RG2'].append(sorted(list(ard['Actions']['RG2'])))
              ard['Actions']['RG2'].add('R::'+rg)
              print("Parent set addition for rg2",rg,ard['Actions']['RG2'])
              parent_sets[nm]['RG2'].append(ard['Actions']['RG2'])
            if len(ard['Actions']['RG3'])>0:
              ards[nm]['RG3'].append(sorted(list(ard['Actions']['RG3'])))
              ard['Actions']['RG3'].add('R::'+rg)
              print("Parent set addition for rg3",rg,ard['Actions']['RG3'])
              parent_sets[nm]['RG3'].append(ard['Actions']['RG3'])
            if len(ard['Actions']['RG4'])>0:
              ards[nm]['RG4'].append(sorted(list(ard['Actions']['RG4'])))
              ard['Actions']['RG4'].add('R::'+rg)
              print("Parent set addition for rg4",rg,ard['Actions']['RG4'])
              parent_sets[nm]['RG4'].append(ard['Actions']['RG4'])
      elif strategy[aw]=='SUB':
        for ss in sxadict[aw]:
          ard['Actions']['SUB']=set()
          for rg in sxadict[aw][ss]:
            for nm in sxadict[aw][ss][rg]:
              for an in sxadict[aw][ss][rg]:
                if an==nm:
                  for ac in sxadict[aw][ss][rg][an]:
                    # Local R actions are absorbed by local A actions
                    if aw=='R' and strategy['A'] is not None and strategy['A']=='SUB' and ss in sxadict['A']:
                      pass
                    # Local R and A actions are absorbed by local W actions
                    elif aw!='W' and strategy['W'] is not None and strategy['W']=='SUB' and ss in sxadict['W']:
                      pass
                    else:
                      # Local W actions cannot be absorbed. We add them.
                      ard['Actions']['SUB'].add(ac)
                  # Local W absorbs local A actions and below (so SUB and RG)
                  if aw=='W' and strategy['A'] is not None and  ss in sxadict['A'] and rg in sxadict['A'][ss] and an in sxadict['A'][ss][rg] and (strategy['A']=='SUB' or (strategy['A']=='RG' and rg in sxadict['A'][ss])):
                    for rg1 in sxadict['A'][ss]:
                      for an1 in sxadict['A'][ss][rg1]:
                        if an1==nm:
                          for ac in sxadict['A'][ss][rg1][an1]:
                            ard['Actions']['SUB'].add(ac)
                  # Local W and local A absorb local R actions (so SUB and RG)
                  if aw!='R' and strategy['R'] is not None and ss in sxadict['R'] and rg in sxadict['R'][ss] and an in sxadict['R'][ss][rg] and (strategy['R']=='SUB' or (strategy['R']=='RG' and rg in sxadict['R'][ss])):
                    for rg1 in sxadict['R'][ss]:
                      for an1 in sxadict['R'][ss][rg1]:
                        if an1==nm:
                          for ac in sxadict['R'][ss][rg1][an1]:
                            ard['Actions']['SUB'].add(ac)
                          break
                  break
          if len(ard['Actions']['SUB'])>0:
            ards[nm]['SUB'].append(sorted(list(ard['Actions']['SUB'])))
            parent_sets[nm]['SUB'].append(ard['Actions']['SUB'])
      elif strategy[aw]=='MG':
        ard['Actions']['MG']=set()
        for ss in sxadict[aw]:
          for rg in sxadict[aw][ss]:
            for nm in sxadict[aw][ss][rg]:
              for an in sxadict[aw][ss][rg]:
                if an==nm:
                  for ac in sxadict[aw][ss][rg][an]:
                    # Local R actions are absorbed by local A actions
                    if aw=='R' and strategy['A'] is not None and strategy['A']=='MG' and ss in sxadict['A'] and rg in sxadict['A'][ss] and an in sxadict['A'][ss][rg]:
                      pass
                    # Local R and A actions are absorbed by local W actions
                    elif aw!='W' and strategy['W'] is not None and strategy['W']=='MG' and ss in sxadict['W'] and rg in sxadict['W'][ss] and an in sxadict['W'][ss][rg]:
                      pass
                    else:
                      # Local W actions cannot be absorbed. We add them.
                      ard['Actions']['MG'].add(ac)
                  # Local W absorbs local A actions and below (so MG, SUB and RG)
                  if aw=='W' and strategy['A'] is not None and strategy['A']=='MG' and ss in sxadict['A'] and rg in sxadict['A'][ss] and an in sxadict['A'][ss][rg]:
                    for ac in sxadict['A'][ss][rg][an]:
                      ard['Actions']['MG'].add(ac)
                  # Local W and local A absorb local R actions (so MG, SUB and RG)
                  if aw!='R' and strategy['R'] is not None and strategy['R']=='MG' and ss in sxadict['R'] and rg in sxadict['R'][ss] and an in sxadict['R'][ss][rg]:
                    for ac in sxadict['R'][ss][rg][an]:
                      ard['Actions']['MG'].add(ac)
                  break
        if len(ard['Actions']['MG'])>0:
          ards[nm]['MG'].append(sorted(list(ard['Actions']['MG'])))
          parent_sets[nm]['MG'].append(ard['Actions']['MG'])
    print("parent sets")
    for aP in parent_sets:
      print("  principal",aP,p2n[aP])
      print("  ..",parent_sets[aP])
    print(" ")
    desired_roles=reason_clusterwide(cluster,parent_sets,debug)
    print("REASONING")
    print(desired_roles)
    print("")
    for s in [ 'MG', 'SUB', 'RG0', 'RG1', 'RG2', 'RG3', 'RG4' ]:
      if s=='MG':
        resolution=2
      elif s=='SUB':
        resolution=3
      #elif s=='RG':
      else:
         resolution=4
      for pset in desired_roles[s]:
        print(s,"pset",list(pset))
        print(s,"desired BEFORE",desired[s])
        partition_permissions(list(pset),resolution,desired[s])
        print(s,"desired AFTER",desired[s])
#      print(" ")
#    print(" ")
    desired_counts= {
            'MG': {},
            'SUB': {},
            'RG0': {},
            'RG1': {},
            'RG2': {},
            'RG3': {},
            'RG4': {}
            }
    for s in [ 'MG', 'SUB', 'RG0', 'RG1', 'RG2', 'RG3', 'RG4' ]:
      if s=='MG':
        resolution=2
      elif s=='SUB':
        resolution=3
      #elif s=='RG':
      else:
         resolution=4
      for g in desired[s]:
        if g not in desired_counts[s]:
          desired_counts[s][g]=1
        else:
          desired_counts[s][g]+=1
      for g in desired_counts[s]:
        cl,res,pr=g.split(':')
        if cl=='write/delete':
          if silhouette[cl][str(resolution)]> desired_sil['write/delete']:
            desired_sil['write/delete']=silhouette[cl][str(resolution)]
      for g in desired_counts[s]:
        cl,res,pr=g.split(':')
        #scaled=desired_sil['write/delete']>=700
        if cl=='action' or cl=='read':
          if silhouette[cl+'_scaleddown'][str(resolution)]>desired_sil[cl]:
            desired_sil[cl]=silhouette[cl+'_scaleddown'][str(resolution)]
    desiredscore=desired_sil['write/delete']+desired_sil['action']+outer_sil['read']  # FOR NOW, because Azure Activity Logs dont capture reads, desired_sil['read'] is set to outer_sil['read']
    print("Desired silhouette=",desiredscore)
    print("")
    print("Cluster condensate:")
    print(desired_roles)
#    print("Individual Role Definitions wihout EQ:",len(ards))
#    print(json.dumps(ards,indent=2))
#    print("Name X Scope X Action")
#    print(json.dumps(axsdict,indent=2))
#    print("...")
#    print("Scope X Name X Action")
#    print(json.dumps(sxadict,indent=2))
  return counts,outerscore,desiredscore

def ml_get_rows(account,table,PK):
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

def ml_ingest():
  import csv
  rz=ml_get_rows(account,run_groundsource,run_partition)
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

  unique_rps = sorted(unique_rps)
  headers = ['Name', 'GWAR', 'SWAR','GWResolution','GAResolution', 'SSResolution','SWResolution','SAResolution' ] + list(unique_rps)
  with open(f"{run_partition}_{dstamp}.csv", 'w', newline='') as file:
    writer = csv.DictWriter(file, fieldnames=headers)
    writer.writeheader()
    for record in data:
        row = {'Name': record['name'], 'GWAR': record['gwar'], 'SWAR': record['swar'], 'GWResolution': record['gwresolution'],'GAResolution': record['garesolution'], 'SSResolution': record['ssresolution'], 'SWResolution': record['swresolution'], 'SAResolution': record['saresolution'] }
        # Set one-hot encoding for rps
        for rps in unique_rps:
            row[rps] = 1 if rps in record['rps'] else 0
        writer.writerow(row)
  print("")
  print(f"CSV file '{run_partition}_{dstamp}.csv' created with {len(headers)} columns.")

def reason_clusterwide(cluster,pset,dendrogram=False):
  import csv
  sol=Solver()
  roles={
    'MG': [],
    'SUB': [],
    'RG0': [],
    'RG1': [],
    'RG2': [],
    'RG3': [],
    'RG4': []
  }
  for scope in [ 'MG', 'SUB', 'RG0','RG1','RG2','RG3','RG4']:
    if os.path.exists(f"dendro-{cluster}-{scope}.csv"):
      os.remove(f"dendro-{cluster}-{scope}.csv")
    sol.push()
    dendroCache={}
    permCache={}
    leftCache={}
    permLeftHistory={}
    permRightHistory={}
    prvh=0
    oldlen=0
    dendroCounter=0
    for pid in pset:
      for scopeset in pset[pid][scope]:
        with open(f"dendro-{cluster}-{scope}.csv", 'a', newline='') as file:
          writer = csv.DictWriter(file, fieldnames=["Equality","left","right"])
          if dendrogram and scope=='MG':
            writer.writeheader()
          cnt=-1
          for perm in scopeset:
            cnt+=1
            zlc={}
            oldzlc={}
            if cnt==0:
              classRepresentative=addPerm(perm)
              sol.add(classRepresentative!=NOPERM)
              permCache[str(classRepresentative)]=1
#              row={'Equality': str(dendroCounter), 'left': str(classRepresentative), 'right': str(classRepresentative)}
#              if dendrogram:
#                writer.writerow(row)
              permLeftHistory[str(dendroCounter)]=str(classRepresentative)
              permRightHistory[str(dendroCounter)]=str(classRepresentative)
            else:
              z3perm=addPerm(perm)
              sol.add(z3perm==classRepresentative)
              if str(classRepresentative) not in dendroCache:
                dendroCache[str(classRepresentative)]=1
                dendroCounter+=1
              permLeftHistory[str(dendroCounter)]=str(z3perm)
              permRightHistory[str(dendroCounter)]=str(classRepresentative)
              permCache[str(z3perm)]=1
              leftCache[str(z3perm)]=1
#              row={'Equality': str(dendroCounter), 'left': str(z3perm), 'right': str(classRepresentative)}
#              if dendrogram:
#                writer.writerow(row)
            if scope in ['RG0','RG1','RG2','RG3','RG4']:
              if dendrogram:
                oldzlc=zlc
                zlc={}
                if sol.check()==sat:
                  mdl=sol.model()
                  for item in mdl:
                    if True:
#                    if str(item)!='No perm':
                      foo=str(mdl[item]).split('val!')
                      equivClass=int(foo[1])
                      sec=str(foo[1])
                      if sec not in zlc and str(item)!='No perm':
                        zlc[sec]=set()
                      if str(item)!='No perm':
                        zlc[sec].add(str(item))
                  zh=hash(str(zlc))
                  if zh!=prvh:# and scope=='RG2':
                    if len(zlc)>oldlen:
                      EQop='C' # class creation
                    elif len(zlc)<oldlen:
                      EQop='M' # transitive marge
                    else:
                      EQop='G' # grow a class
                    print('"id": '+str(dendroCounter)+', "op": "'+EQop+'", "term": "'+permLeftHistory[str(dendroCounter)]+'" ,[',end='')
                    row={'Equality': dendroCounter, 'left': str(permLeftHistory[str(dendroCounter)]), 'right': str(permRightHistory[str(dendroCounter)])}
                    writer.writerow(row)
                    zbuf=''
                    for alc in zlc:
                      zbuf+=str(zlc[alc])+','
                    prvh=zh
                    zbuf=zbuf[:-1]+"]"
                    print(zbuf)
                    oldlen=len(zlc)
              dendroCounter+=1
#          for p in permCache.keys():
#            if p not in leftCache and p not in dendroCache:
#              row={'Equality': str(dendroCounter), 'left': str(p), 'right': str(p)}
#              if dendrogram:
#                writer.writerow(row)
#              dendroCounter+=1
    localClasses={}
    stripped={}
    if sol.check()==sat:
      mdl=sol.model()
      for item in mdl:
        if str(item)!='No perm':
          foo=str(mdl[item]).split('val!')
          equivClass=int(foo[1])
          sec=str(foo[1])
          if sec not in localClasses:
            localClasses[sec]=set()
          localClasses[sec].add(str(item))
      for alc in localClasses:
        if alc not in stripped:
          stripped[alc]=set()
        for alcm in localClasses[alc]:
            if str(alcm[1:3])!='::':
              stripped[alc].add(alcm) 
        roles[scope].append(stripped[alc])
    else:
      print("reason clusterwide: UNSAT")
    sol.pop()
  return roles

cluster_sample= { "p1": {'MG': set(), 'SUB': set(), 'RG0': [{'a'}, {'b', 'c'}, {'h'}], 'RG1': set(), 'RG2': set(), 'RG3': set(), 'RG4': set()},
        "p2": {'MG': set(), 'SUB': set(), 'RG0': [{'e', 'f', 'g'}, {'c', 'd'}, {'h'}], 'RG1': set(), 'RG2': set(), 'RG3': set(), 'RG4': set()},
        "p3": {'MG': set(), 'SUB': set(), 'RG0': [{'b'}, {'f', 'a'}, {'h'}], 'RG1': set(), 'RG2': set(), 'RG3': set(), 'RG4': set()}
                }

NOPERM=addPerm('No perm')

#desired_roles=reason_clusterwide("sample",cluster_sample,True)
#print(desired_roles)
#sys.exit()
build_partition=new_partition()
print("build partition",build_partition)
print("run partition",run_partition)
print("ground truth build table",build_groundsource)
print("golden source build table",build_goldensource)
print("ground truth run table",run_groundsource)
print("golden source run table",run_goldensource)
print("unused",unused)
print("orphans",orphans)
timeNow=datetime.today().strftime('%Y-%m-%dT%H:%M:%S.%fZ')
timeBack=(datetime.today()-timedelta(days=logsRetention)).strftime('%Y-%m-%dT%H:%M:%S.%fZ')
print("time now:",timeNow)
print("time back:",timeBack)
