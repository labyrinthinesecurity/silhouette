#!/usr/bin/python3
from native import *
import subprocess
import csv,os
import math
import argparse
from datetime import datetime
from ultrametry import *

current_date = datetime.now()
current_timestamp = current_date.strftime("%Y-%m-%d")

parser = argparse.ArgumentParser()
parser.add_argument('--single', type=str, help='display stats for just one SPN id: SINGLE')
parser.add_argument('--version', required=False, action="store_true", help='show version and exit')
parser.add_argument('--verbose', required=False, action="store_true", help='toggle debugging output')
parser.add_argument("--apps", required=False, action="store_true", help="ignore managed identities")
parser.add_argument("--mis", required=False, action="store_true", help="ignore applications")
parser.add_argument('--frs', required=False, action="store_true", help='reserved for future use')
parser.add_argument("--live", required=False, action="store_true", help="refresh local Silhouette caches (slow, but accurate)")
args = parser.parse_args()

if args.live is None:
  args.live=False

warpermdict={}
spnscache={}
spn={}
membership={}
gperms={}
frs={}
groups={}
group={}
hierarchy = None

silhouette={
        'superadmin': {
            '0': 0,     # none
            '1': 900,   # tenant
            '2': 800,   # mgmt group
            '3': 700,   # subscription
            '4': 300,   # RG
            '6': 200,   # resource
            '8': 100,   # subresource
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

def classify_da_permission(permission,notlowperms,notsegments):
    lowperm = permission.lower()
    segments = lowperm.split("/")

    assigner=False
    designer=False

    if notlowperms and (("microsoft.authorization/" in notlowperms[0]) or ("microsoft.managedidentity/" in notlowperms[0])):
        return None 
    elif ("microsoft.authorization/" not in lowperm) and ("microsoft.managedidentity/" not in lowperm):
        return None 

    if permission == "*" or permission == "/*":
        if notlowperms and ("microsoft.authorization/roleassignments" not in notlowperms[0] and "microsoft.authorization/roledefinitions" not in notlowperms[0] and "microsoft.managedidentity/" not in notlowperms[0]):
          return "superadmin"
        else:
          return "superadmin"

    if notlowperms and ("microsoft.authorization/roleassignments" in lowperm and "microsoft.authorization/roleassignments" not in notlowperms[0]):
        assigner=True
    elif "microsoft.authorization/roleassignments" in lowperm:
        assigner=True

    if notlowperms and ("microsoft.authorization/roledefinitions" in lowperm and "microsoft.authorization/roledefinitions" not in notlowperms[0]):
        designer=True
    elif "microsoft.authorization/roledefinitions" in lowperm:
        designer=True

    if "microsoft.managedidentity/" in lowperm:
      if notlowperms and ("/assign/action" in lowperm and "/assign/action" not in notlowperms[1]):
        assigner=True
    elif "/assign/action" in lowperm:
        assigner=True

    if "microsoft.authorization/diagnosticsettings" in lowperm:
        return None

    if "microsoft.authorization/locks" in lowperm:
        return None 

    if "microsoft.authorization/polic" in lowperm:
        return None

    if "microsoft.authorization/provideroperations" in lowperm:
        return None 

    if any("write" in segment or "delete" in segment for segment in segments):
        if designer and not(assigner):
          return "define"
        if assigner and not(designer):
          return "assign"
        if assigner and designer:
          return "superadmin"
        return None

    if segments[-1:][0]=="*":
        if designer and not(assigner):
          return "define"
        if assigner and not(designer):
          return "assign"
        if assigner and designer:
          return "superadmin"
        return None

    if any("action" in segment for segment in segments):
        if designer and not(assigner):
          return "define"
        if assigner and not(designer):
          return "assign"
        if assigner and designer:
          return "superadmin"
        return None 

    if any("read" in segment for segment in segments):
        return None
    return None


def classify_war_permission(permission,resolution,verbose):
    global warpermdict
    lowperms = permission.lower()
    segments = lowperms.split("/")

    if segments[0]!='*':
      rp=segments[0]
    else:
      rp=None

    if "microsoft.support/" in lowperms or "microsoft.resourcehealth/" in lowperms or "microsoft.alertsmanagement/" in lowperms or "microsoft.insights/" in lowperms or "microsoft.operationalinsights/" in lowperms or "microsoft.operationsmanagement" in lowperms or "microsoft.consumption/" in lowperms or "microsoft.costmanagement/" in lowperms:
        if verbose:
          wpd=permission+":R:"+str(resolution)
          if wpd not in warpermdict:
            warpermdict[wpd]=0
        return "read",segments[0]
    if permission == "*" or permission == "/*":
      if resolution>=8:
        if verbose:
          wpd=permission+":A:"+str(resolution)
          if wpd not in warpermdict:
            warpermdict[wpd]=0
        return "action",segments[0]
      elif resolution>=6:
        if verbose:
          wpd=permission+":W:"+str(resolution)
          if wpd not in warpermdict:
            warpermdict[wpd]=0
        return "write/delete",segments[0]
      else:
        if verbose:
          wpd=permission+":S:"+str(resolution)
          if wpd not in warpermdict:
            warpermdict[wpd]=0
        return "superadmin",segments[0]

    if "microsoft.authorization/denyassignments" in lowperms:
        return "none",None

    if "microsoft.authorization/elevateaccess" in lowperms:
        return "none",None

    if "microsoft.authorization/classicadministrators" in lowperms:
        return "none",None

    if "microsoft.authorization/roleassignments" in lowperms:
        return "none",None

    if "microsoft.authorization/roledefinitions" in lowperms:
        return "none",None

    if "microsoft.authorization/roleeligibilityschedule" in lowperms:
        return "none",None

    if "microsoft.authorization/rolemanagementpolic" in lowperms:
        return "none",None

    if "microsoft.authorization/*" in lowperms:
        return "read",segments[0]

    if "microsoft.managedidentity/*" in lowperms:
        return "read",segments[0]

    if "microsoft.managedidentity/" in lowperms:
      if "assign/action" in lowperms:
        return "read",segments[0]

    if segments[-1:][0]=="*":
        if verbose:
            wpd=permission+":S:"+str(resolution)
            if wpd not in warpermdict:
              warpermdict[wpd]=0
              #print(permission,"S",resolution)
        return "superadmin",rp
    if "write" in segments[-1:][0].lower() or "delete" in segments[-1:][0].lower():
        if verbose:
          wpd=permission+":W:"+str(resolution)
          if wpd not in warpermdict:
            warpermdict[wpd]=0
            #print(permission,"W",resolution)
        return "write/delete",rp
    elif "action" in segments[-1:][0].lower():
        if verbose:
          wpd=permission+":A:"+str(resolution)
          if wpd not in warpermdict:
            warpermdict[wpd]=0
            #print(permission,"A",resolution)
        return "action",rp
    elif "read" in segments[-1:][0].lower():
        if verbose:
          wpd=permission+":R:"+str(resolution)
          if wpd not in warpermdict:
            warpermdict[wpd]=0
            #print(permission,"R",resolution)
        return "read",rp
    if verbose:
      wpd=permission+":U:"+str(resolution)
      if wpd not in warpermdict:
        warpermdict[wpd]=0
        #print(permission,"U",resolution)
    return "unknown",None



def partition_permissions(permissions,notpermissions,resolution):
    war_perms=set([])
    da_perms=set([])
    notlowperms = [s.lower() for s in notpermissions]
    notsegments = [s.split("/") for s in notlowperms]
    for permission in permissions:
        cwp,rp=classify_war_permission(permission,resolution,False)
        war_item=cwp+":"+str(resolution)+":"+permission
        war_perms.add(war_item)
        cdp=classify_da_permission(permission,notlowperms,notsegments)
        if cdp:
          da_item=cdp+":"+permission
          da_perms.add(da_item)
    return war_perms,da_perms

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

def probe_group_perms(gid,gtoken):
  query='''
authorizationresources
| where type == "microsoft.authorization/roleassignments"
| where tostring(properties.principalType) == "Group"
| where tostring(properties.principalId) == "
'''
  query=query[:-1]+gid
  query=query+'''"
| summarize count()
'''
  results,gtoken = fetch_resource_graph_results(query=query,token=gtoken)
  if results is not None and len(results)>0:
    if 'count_' in results[0]:
      return results[0]['count_'],gtoken
    else:
      print("ERROR. _count not found")
      sys.exit()
  return 0,gtoken

def fetch_group_perms(gid,gtoken,current,total):
  print(f"  ({current}/{total}) FETCHING roles of group",gid)
  query='''
authorizationresources
| where type == "microsoft.authorization/roleassignments"
| where tostring(properties.principalType) == "Group"
| where tostring(properties.principalId) == "
'''
  query=query[:-1]+gid
  query=query+'''"
| extend pid = tostring(properties.principalId)
| extend scope = tostring(properties.scope)
| extend rdid = tostring(properties.roleDefinitionId)
| extend raid = tostring(id)
| join kind = inner (authorizationresources
    | where ["type"] has "roledefinitions"
    | distinct tostring(properties.roleName), ["id"],tostring(properties.permissions[0].actions),tostring(properties.permissions[0].notActions),tostring(properties.permissions[0].dataActions),tostring(properties.permissions[0].notDataActions)
    ) on $left.rdid == $right.["id"]
| extend combinedRole = pack('roleName',tostring(properties_roleName),'scope',tostring(properties.scope),'raid',['raid'],'rdid', ['rdid'], 'actions', tostring(properties_permissions_0_actions), 'notActions',properties_permissions_0_notActions,'dataActions',properties_permissions_0_dataActions,'notDataActions',properties_permissions_0_notDataActions )
| summarize make_set(combinedRole) by pid
'''
  results,gtoken = fetch_resource_graph_results(query=query,token=gtoken)
  return results,gtoken

def fetch_combined(pid):
  if pid:
    query='''
authorizationresources
| where type == "microsoft.authorization/roleassignments"
| where tostring(properties.principalType) == "ServicePrincipal"
| extend pid = tostring(properties.principalId)
| where pid == "
'''
    query=query[:-1]+pid
    query=query+'''"
| extend scope = tostring(properties.scope)
| extend rdid = tostring(properties.roleDefinitionId)
| extend raid = tostring(id)
| join kind = inner (authorizationresources
    | where ["type"] has "roledefinitions"
    | distinct tostring(properties.roleName), ["id"],tostring(properties.permissions[0].actions),tostring(properties.permissions[0].notActions),tostring(properties.permissions[0].dataActions),tostring(properties.permissions[0].notDataActions)
    ) on $left.rdid == $right.["id"]
| extend combinedRole = pack('roleName',tostring(properties_roleName),'scope',tostring(properties.scope),'raid',['raid'],'rdid', ['rdid'], 'actions', tostring(properties_permissions_0_actions), 'notActions',properties_permissions_0_notActions,'dataActions',properties_permissions_0_dataActions,'notDataActions',properties_permissions_0_notDataActions )
| summarize make_set(combinedRole) by pid
'''
    results,gtoken = fetch_resource_graph_results(query=query,token=None)
    return results
  else:
    query='''
authorizationresources
| where type == "microsoft.authorization/roleassignments"
| where tostring(properties.principalType) == "ServicePrincipal"
| extend pid = tostring(properties.principalId)
| extend scope = tostring(properties.scope)
| extend rdid = tostring(properties.roleDefinitionId)
| extend raid = tostring(id)
| join kind = inner (authorizationresources
    | where ["type"] has "roledefinitions"
    | distinct tostring(properties.roleName), ["id"],tostring(properties.permissions[0].actions),tostring(properties.permissions[0].notActions),tostring(properties.permissions[0].dataActions),tostring(properties.permissions[0].notDataActions)
    ) on $left.rdid == $right.["id"]
| extend combinedRole = pack('roleName',tostring(properties_roleName),'scope',tostring(properties.scope),'raid',['raid'],'rdid', ['rdid'], 'actions', tostring(properties_permissions_0_actions), 'notActions',properties_permissions_0_notActions,'dataActions',properties_permissions_0_dataActions,'notDataActions',properties_permissions_0_notDataActions )
| summarize make_set(combinedRole) by pid
  '''
    results,gtoken = fetch_resource_graph_results(query=query,token=None)
    print("TOTAL number of roles retrieved:",len(results))
    print()
    with open("ARG.json", "w") as file:
      json.dump(results, file)
    return None

def calculate_WAR(identity,minW,minA,minR):
  template={
      'write/delete': minW,
      'action': minA,
      'none': 0,
      'unknown': 0,
      'read':minR
  }
  if len(identity['da_permset'])>0:
    if args.verbose:
      print("DA INFORMATION:",identity['da_permset'])
    for da in identity['da_permset']:
      if "assign" in da:
        identity['A']=True
      elif "define" in da:
        identity['D']=True
  if len(identity['war_permset'])==0:
    return
  for item in identity['war_permset']:
    if item not in identity['golden_counts']:
      identity['golden_counts'][item]=1
    else:
      identity['golden_counts'][item]+=1
  someSuperAdmin=False
  scaled=False
  for g in identity['golden_counts']:
    cl,res,pr=g.split(':')
    if cl=='superadmin':
      if int(res)<=4:  # superadmin scopes at Tenant, MG, sub or RG scope can assign or define roles
        someSuperAdmin=True
      if silhouette[cl][str(res)]> template['write/delete']:
        template['write/delete']=silhouette[cl][str(res)]
      if scaled:
        template['action']=silhouette['action_scaleddown'][str(res)]
        template['read']=silhouette['read_scaleddown'][str(res)]
      else:
        template['action']=silhouette['action'][str(res)]
        template['read']=silhouette['read'][str(res)]
    elif cl=='write/delete':
      if silhouette[cl][str(res)]> template['write/delete']:
        template['write/delete']=silhouette[cl][str(res)]
  for g in identity['golden_counts']:
    cl,res,pr=g.split(':')
    if cl=='action' or cl=='read':
        if scaled:
          if silhouette[cl+'_scaleddown'][str(res)]>template[cl]:
            template[cl]=silhouette[cl+'_scaleddown'][str(res)]
        else:
          if silhouette[cl][str(res)]>template[cl]:
            template[cl]=silhouette[cl][str(res)]
  identity['WAR']=template['write/delete']+template['action']+template['read']
  if identity['WAR']>=400: 
    identity['A']=True
    identity['D']=True

def generate_WAR_norms(single,combined):
  if single:
    bulk=combined
    spnscache={}
    spnscache[single]={}
    spnscache[single]['servicePrincipalType']=""
    spnscache[single]['displayName']=""
  else:
    if os.path.exists("ARG.json"):
      with open("ARG.json", "r") as file:
        bulk=json.load(file)
    else:
      print("ERROR: please load RBAC roles from ARG by running fetch_combined first")
      sys.exit()
    print("loaded",len(bulk),"assigned SPN RBAC roles from Azure Resource Graph")
    if os.path.exists("spns_cache.json"):
      with open("spns_cache.json", "r") as file:
        spnscache=json.load(file)
    else:
      print("ERROR: please load SPNs from Entra by running gneerate_spns_cache first")
      sys.exit()
    print("loaded",len(spnscache),"SPNs from Entra")
  roles=set([])
  for role in bulk:
    roles.add(role['pid'])
  roles2=set([])
  gtoken=None
  t=0
  for pid in spnscache:
    if pid not in roles:
      t+=1
      roles2.add(pid)
  if single is None and args.verbose:
    print(t,"SPNs with not direct role assignements to inspect")
  s=-1
  roles2=sorted(roles2)
  for pid in roles2:
    s+=1
#    if s>100:
#      break
    if s%10==1:
      print(f"{s}/{t}")
    if s%100==0:
      gtoken=None    
      token=None
    if args.verbose:
      print("seeking nondirect roles for",pid,end=' ')
    if pid in membership:
      g0=membership[pid]
    else:
      g0,token=get_groups_of(pid,'ServicePrincipal',token)
      membership[pid]=g0
    if g0 and 'value' in g0:
      g0v=g0['value']
      if len(g0v)==0:
        if args.verbose:
          print("  ",pid,"has no groups hence no non-direct roles")
        continue
      pr={}
      pr['pid']=pid
      pr['set_combinedRole']=[]
      if pr not in bulk:
        bulk.append(pr)
      groupsof=set([])
      for ag in g0v:
        if args.verbose:
          print("  ",pid,"is member of",ag['id'])
        groupsof.add(ag['id'])
        if ag['id'] not in groups:
          if args.verbose:
            print("    (this group is not cached in groups because it is either just discovered or has Azure perms)")
          count,gtoken=probe_group_perms(ag['id'],gtoken)
          print(f"  ({s}/{t}) PROBING group",ag['id'],"rdids",count)
          if count>0: # the SPN is member of a group with Azure permissions
            if args.verbose:
              print(f"({s}/{t}) adding SPN",pid,"since it has",count,"Azure perms through group",ag['id'])
          else: # the group has no azure permissions, let's cache this group if necessary
            if args.verbose:
              print("  group",ag['id'],"has no Azure permissions. We store it empty in the groups cache",count)
            groups[ag['id']]={}
            groups[ag['id']]['war_permset']=[]
            groups[ag['id']]['da_permset']=[]
            groups[ag['id']]['golden_counts']={}
            groups[ag['id']]['dataActions']=False
            groups[ag['id']]['dataActions_dict']={}
            groups[ag['id']]['actions_dict']={}
            groups[ag['id']]['rdids']=[]
            groups[ag['id']]['resolutions']=[]
            groups[ag['id']]['WAR']=0
            groups[ag['id']]['D']=False
            groups[ag['id']]['A']=False
        else:
          if args.verbose:
            print(" group ",ag['id'],"was already cached with",len(groups[ag['id']]['rdids']),"rdids and SPN",pid,"was already cached")
    else:
      if args.verbose:
        print("  ",pid,"has no groups hence no non-direct roles")
  del(roles)
  del(roles2)
  b=len(bulk)
  if single is None:
    print(b,"SPNs to score in total")
  token=None
  gtoken=None
  c=-1
  for role in bulk:
    c+=1
#    if c>200:
#      break
    if args.verbose:
      print("  handling",role['pid'])
    if c%10==1:
      print(f"{c}/{b}")
    if role['pid'] in spnscache:
      if spnscache[role['pid']]['servicePrincipalType']!='Application':
        if args.apps:
          if args.verbose:
            print("  ignoring non-app SPN",role['pid'])
          continue
      if spnscache[role['pid']]['servicePrincipalType']!='ManagedIdentity':
        if args.mis:
          if args.verbose:
            print("  ignoring non-MI SPN",role['pid'])
          continue
      if role['pid'] not in spn:
        if args.verbose:
          print(role['pid'],"not in encountered spns, creating dict entry")
        spn[role['pid']]={}
        spn[role['pid']]['war_permset']=[]
        spn[role['pid']]['da_permset']=[]
        spn[role['pid']]['golden_counts']={}
        spn[role['pid']]['memberships']=None
        spn[role['pid']]['groups']=[]
        spn[role['pid']]['uras']=0
        spn[role['pid']]['iras']=0
        spn[role['pid']]['WAR']=0
        spn[role['pid']]['A']=False
        spn[role['pid']]['D']=False
        spn[role['pid']]['dataActions']=False
        spn[role['pid']]['dataActions_dict']={}
        spn[role['pid']]['actions_dict']={}
        spn[role['pid']]['rdids']=[]
        spn[role['pid']]['resolutions']=[]
        spn[role['pid']]['minW']=0
        spn[role['pid']]['minA']=0
        spn[role['pid']]['minR']=0
      spn[role['pid']]['type']=spnscache[role['pid']]['servicePrincipalType']
      spn[role['pid']]['name']=spnscache[role['pid']]['displayName']
    else:
      if args.verbose:
        print(role['pid'],"not in Entra, so we may ignore it")
      continue # spn not in Entra, we can ignore it safely
    if c%100==0:
      token=None
      gtoken=None
    groupsof=None
    if spn[role['pid']]['memberships'] is None:
      if role['pid'] in membership:
        g0=membership[role['pid']]
      else:
        g0,token=get_groups_of(role['pid'],'ServicePrincipal',token)
        membership[role['pid']]=g0
      if g0 and 'value' in g0:
        g0v=g0['value']
        groupsof=set([])
        rdids=[]
        resolutions=[]
        for ag in g0v:
          groupsof.add(ag['id'])
          if ag['id'] not in groups:
            if args.verbose:
              print("  group ",ag['id'],"not in groups cache, creating dict entry")
            if ag['id'] not in gperms:
              g,gtoken=fetch_group_perms(ag['id'],gtoken,c,b)
              gperms[ag['id']]=g
            else:
              g=gperms[ag['id']]
            groups[ag['id']]={}
            groups[ag['id']]['war_permset']=[]
            groups[ag['id']]['da_permset']=[]
            groups[ag['id']]['golden_counts']={}
            groups[ag['id']]['dataActions']=False
            groups[ag['id']]['dataActions_dict']={}
            groups[ag['id']]['actions_dict']={}
            groups[ag['id']]['rdids']=[]
            groups[ag['id']]['resolutions']=[]
            groups[ag['id']]['WAR']=0
            groups[ag['id']]['D']=False
            groups[ag['id']]['A']=False
            resolution=8
            for gr in g:
              for combined in gr['set_combinedRole']:
                _,rrr=extract_azure_resource_details(combined['scope'])
                if rrr>=5: # res or subres
                  r=2
                elif rrr>=3: # sub or RG
                  r=1
                else: # tenant or MG
                  r=0
                rdid=combined['rdid'].split('RoleDefinitions/')
                cnt=-1
                if rdid[1] in rdids:
                  for rdd in rdids:
                    cnt+=1
                    if rdd==rdid[1]:
                      break
                  if r<resolutions[cnt]:
                    #print("  +=+= GROUP CUMUL found a lower scope",r,"<",resolutions[cnt],"at counter",cnt,"rdid",rdid[1])
                    resolutions[cnt]=min(r,resolutions[cnt])
                else:
                  rdids.append(rdid[1])
                  resolutions.append(r)
                if rdid[1] not in groups[ag['id']]['rdids']:
                  groups[ag['id']]['rdids'].append(rdid[1])
                  groups[ag['id']]['resolutions'].append(r)
                else:
                  cnt=-1
                  for rdd in groups[ag['id']]['rdids']:
                    cnt+=1
                    if rdd==rdid[1]:
                      break
                  if r<groups[ag['id']]['resolutions'][cnt]:
                    #print("  +=+= GROUP found a lower scope",r,"<", groups[ag['id']]['resolutions'][cnt],"at counter",cnt,"rdid",rdid[1])
                    groups[ag['id']]['resolutions'][cnt]=min(r,groups[ag['id']]['resolutions'][cnt])
                if 'actions' in combined:
                  actions=json.loads(combined['actions'])
                  if len(actions)>0:
                    if combined['scope'] not in groups[ag['id']]['actions_dict']:
                      groups[ag['id']]['actions_dict'][combined['scope']]=[]
                    for a in actions:
                      if a not in groups[ag['id']]['actions_dict'][combined['scope']]:
                        if args.verbose:
                          print("CTRL action groups adding",a,"to scope",combined['scope'])
                        groups[ag['id']]['actions_dict'][combined['scope']].append(a)
                else:
                  actions=[]
                if 'notActions' in combined:
                  notActions=json.loads(combined['notActions'])
                else:
                  notActions=[]
                if 'dataActions' in combined:
                  dactions=json.loads(combined['dataActions'])
                  if len(dactions)>0:
                    groups[ag['id']]['dataActions']=True
                    if combined['scope'] not in groups[ag['id']]['dataActions_dict']:
                      groups[ag['id']]['dataActions_dict'][combined['scope']]=[]
                    for da in dactions:
                      if da not in groups[ag['id']]['dataActions_dict'][combined['scope']]:
                        if args.verbose:
                          print("DATA action groups adding",da,"to scope",combined['scope'])
                        groups[ag['id']]['dataActions_dict'][combined['scope']].append(da)
                else:
                  dactions=[]
                _,resolution=extract_azure_resource_details(combined['scope'])
                war_perms,da_perms=partition_permissions(actions,notActions,resolution)
                for ap in war_perms:
                  if ap not in groups[ag['id']]['war_permset']:
                    groups[ag['id']]['war_permset'].append(ap)
                for ap in da_perms:
                  if ap not in groups[ag['id']]['da_permset']:
                    groups[ag['id']]['da_permset'].append(ap)
            calculate_WAR(groups[ag['id']],0,0,0)
            if args.verbose:
              print("  group",ag['id'],"has WAR norm",groups[ag['id']]['WAR'])
          else:
            if args.verbose:
              print("  group ",ag['id'],"was in groups cache, updating cache entry with",len(groups[ag['id']]['rdids']),"rdids")
            for r in groups[ag['id']]['rdids']:
              rdids.append(r)
            for rz in groups[ag['id']]['resolutions']:
              resolutions.append(rz)
        if len(groupsof)>0:
          spn[role['pid']]['memberships']=len(groupsof)
          spn[role['pid']]['groups']=list(groupsof)
          spn[role['pid']]['rdids']=rdids
          spn[role['pid']]['resolutions']=resolutions
          for g in groupsof:
            gW=int(math.floor(groups[g]['WAR']/100))
            gA=int(math.floor(groups[g]['WAR']-100*gW)/10)
            gR=int(groups[g]['WAR']-100*gW-10*gA)
            if args.verbose:
              print("  group W.A.R.",groups[g]['WAR'],gW,gA,gR)
            spn[role['pid']]['minW']=max(spn[role['pid']]['minW'],gW)
            spn[role['pid']]['minA']=max(spn[role['pid']]['minA'],gW)
            spn[role['pid']]['minR']=max(spn[role['pid']]['minR'],gW)
          if len(rdids)>0 and args.verbose:
            print(role['pid'],"has",len(groupsof),"groups with",len(rdids),"rdids")
        else:
          spn[role['pid']]['memberships']=0
          if args.verbose:
            print(role['pid'],"hasnt got any group with Azure assigments")
      else:
        spn[role['pid']]['memberships']=0
        if args.verbose:
          print(role['pid'],"hasnt got any group at all")
    if len(spn[role['pid']]['rdids'])>0:
      for gid in spn[role['pid']]['groups']:
        spn[role['pid']]['dataActions']=(spn[role['pid']]['dataActions'] or groups[gid]['dataActions'])
        for scope in groups[gid]['actions_dict']:
          for a in groups[gid]['actions_dict'][scope]:
            if scope not in spn[role['pid']]['actions_dict']:
              spn[role['pid']]['actions_dict'][scope]=[]
            if a not in spn[role['pid']]['actions_dict'][scope]:
              if args.verbose:
                print("CTRL action add",a,"via group",gid,"to scope",scope)
              spn[role['pid']]['actions_dict'][scope].append(a)
        for scope in groups[gid]['dataActions_dict']:
          for da in groups[gid]['dataActions_dict'][scope]:
            if scope not in spn[role['pid']]['dataActions_dict']:
              spn[role['pid']]['dataActions_dict'][scope]=[]
            if da not in spn[role['pid']]['dataActions_dict'][scope]:
              if args.verbose:
                print("DATA action add",da,"via group",gid,"to scope",scope)
              spn[role['pid']]['dataActions_dict'][scope].append(da)
        if len(groups[gid]['war_permset'])>0:
          for r in groups[gid]['war_permset']:
            if r not in spn[role['pid']]['war_permset']:
              spn[role['pid']]['war_permset'].append(r)
        if len(groups[gid]['da_permset'])>0:
          for r in groups[gid]['da_permset']:
            if r not in spn[role['pid']]['da_permset']:
              spn[role['pid']]['da_permset'].append(r)
      spn[role['pid']]['iras']=len(spn[role['pid']]['rdids'])
      if args.verbose and (args.single is None):
        print(role['pid'],"GM rdids BEFORE direct rdids",spn[role['pid']]['iras'])
        print("  ",spn[role['pid']]['rdids'])
        print("  ",spn[role['pid']]['resolutions'])
    newrdids=set([])
    for combined in role['set_combinedRole']:
      _,rrr=extract_azure_resource_details(combined['scope'])
      if rrr>=5: # res or subres
        r=2
      elif rrr>=3: # sub or RG
        r=1
      else: # tenant or MG
        r=0
      rdid=combined['rdid'].split('RoleDefinitions/')
      if rdid[1] not in spn[role['pid']]['rdids']:
        spn[role['pid']]['rdids'].append(rdid[1])
        spn[role['pid']]['resolutions'].append(r)
        newrdids.add(rdid[1])
        spn[role['pid']]['uras']+=1
      else:
        cnt=-1
        for ri in spn[role['pid']]['rdids']:
          cnt+=1
          if ri==rdid[1]:
            if r<spn[role['pid']]['resolutions'][cnt]:
              #print("  ",spn[role['pid']],"+=+= SPN found a lower scope",r,"<",spn[role['pid']]['resolutions'][cnt],"at counter",cnt,"rdid",rdid[1])
              spn[role['pid']]['resolutions'][cnt]=min(r,spn[role['pid']]['resolutions'][cnt])
      if 'actions' in combined:
        actions=json.loads(combined['actions'])
        if len(actions)>0:
          if combined['scope'] not in spn[role['pid']]['actions_dict']:
            spn[role['pid']]['actions_dict'][combined['scope']]=[]
          for a in actions:
            if a not in spn[role['pid']]['actions_dict'][combined['scope']]:
              if args.verbose:
                print("CTRL action spn add action",a,"to scope",combined['scope'])
              spn[role['pid']]['actions_dict'][combined['scope']].append(a)
      else:
        actions=[]
      if 'notActions' in combined:
        notActions=json.loads(combined['notActions'])
      else:
        notActions=[]
      if 'dataActions' in combined:
        dactions=json.loads(combined['dataActions'])
        if len(dactions)>0:
          spn[role['pid']]['dataActions']=True
          if combined['scope'] not in spn[role['pid']]['dataActions_dict']:
            spn[role['pid']]['dataActions_dict'][combined['scope']]=[]
          for da in dactions:
            if da not in spn[role['pid']]['dataActions_dict'][combined['scope']]:
              if args.verbose:
                print("DATA action spn add action",da,"to scope",combined['scope'])
              spn[role['pid']]['dataActions_dict'][combined['scope']].append(da)
      else:
        dactions=[]
      _,resolution=extract_azure_resource_details(combined['scope'])
      war_perms,da_perms=partition_permissions(actions,notActions,resolution)
      for item in war_perms:
        if item not in spn[role['pid']]['war_permset']:
          spn[role['pid']]['war_permset'].append(item)
      for item in da_perms:
        if item not in spn[role['pid']]['da_permset']:
          spn[role['pid']]['da_permset'].append(item)
    if len(newrdids)>0 and args.verbose:
      print(role['pid'],"extra, inherited rdids",len(newrdids))
      print("  ",newrdids)
  spn_to_delete=set()
  for s in spn:
    calculate_WAR(spn[s],spn[s]['minW'],spn[s]['minA'],spn[s]['minR'])
    pairs=None
    permiplets=None
    infimum=None
    infimum_h=''
    infimum_p=None
    blast_radii={}
    permiplets={}
    if spn[s]['dataActions']:
      for shunt in shunts:
        print("EXAMINING HIERARCHY",shunt)
        permiplets[shunt] = group_permiplets_by_action_scope(hierarchy,spn[s]['dataActions_dict'], collapsed=False)
        ps = list(permiplets[shunt])
        if len(ps) == 1:
          scope, depth, impact = ps[0]
          blast_radii[shunt] = float(impact) / (2 ** (2 * float(depth) + 1))
          if args.verbose:
            print("  (no pairs found)")
            print("  blast radius:",blast_radii[shunt])
        else:
          blast_radii[shunt],pairs=process_pairs(shunts[shunt],permiplets[shunt])
          if args.verbose:
            print("  maximum pair:")
          found=False
          lca=None
          lca_depth=None
          for p in pairs:
            if p['distance']==blast_radii[shunt]:
              if args.verbose:
                print("  P1>",p['p1'][0])
              if 'p2' in p:
                if args.verbose:
                  print("  P2>",p['p2'][0])
                _,lca_depth = least_common_ancestor(shunts[shunt], p['p1'][0], p['p2'][0], collapsed=False, verbose =True)
              found=True
              break
          if args.verbose:
            print("  blast radius:",blast_radii[shunt])
      infimum=2.0
      print("blast radii:")
      print(blast_radii)
      for br in blast_radii:
        print("  BR",br)
        if blast_radii[br]<infimum:
          infimum=blast_radii[br]
          infimum_h=br
          infimum_p=permiplets[br]
    if args.verbose and infimum is not None:
      print("infimum blast radius:",infimum,"in",infimum_h,"hierarchy for ",s)
      print()
    if args.verbose and single==False and infimum is not None:
      print(f"  blast radius of {s}: {infimum}")
    spn[s]['blast_radius']=infimum
    if spn[s]['WAR']<1 and spn[s]['A'] == False and spn[s]['D'] == False and spn[s]['dataActions'] == False:
      if args.verbose:
        print("DELETING",s,"because it has no Azure perms")
        spn_to_delete.add(s)
    elif args.frs:
      if s not in frs:
        frs[s]=set([])
      if args.verbose and (args.single is None):
        print("  adding RDIDS of SPN",s,"to FRS",len(spn[s]['rdids']))
      cnt=-1
      for rd in spn[s]['rdids']:
        cnt+=1
        rdscope=rd+":"+str(spn[s]['resolutions'][cnt])
        frs[s].add(rdscope)
      if args.verbose and (args.single is None):
        print("  resulting FRS for SPN",s,"is",frs[s])
  for sd in spn_to_delete:
    del(spn[sd])
  if args.frs:
    headers = ["pid", "rdid"]
    with open("AZURE_FRS.csv", "w", newline="") as f:
      writer = csv.writer(f)
      writer.writerow(headers)
      for f in frs:
        for r in frs[f]:
          row=[f,r]
          writer.writerow(row)
  if single:
    if len(spn)==0:
      print("  ERROR. Cannot find this SPN.")
      sys.exit()
    if 'displayName' in spn[s]:
      print("  name:",spn[s]['displayName'])
    if 'servicePrincipalType' in spn[s]:
      print("  type:",spn[s]['servicePrincipalType'])
    print("  unique role assignments:",spn[s]['uras'])
    print("  group memberships:",spn[s]['memberships'])
    print("")
    print("  Azure Control Plane> WAR norm:",spn[s]['WAR'])
    print("  Entra Control Plane> can assign roles:",spn[s]['A'])
    print("  Entra Control Plane> can define roles:",spn[s]['D'])
    '''
    if args.verbose:
      for item in spn[s]['war_permset']:
        print("  Azure Control Plane>",item)
      print("")
      cnt=-1
      for item in spn[s]['rdids']:
        cnt+=1
        print("  Azure Control Plane>",item+":"+str(spn[s]['resolutions'][cnt]))
    '''
    print("")
    print("  Azure Data Plane> blast radius:",spn[s]['blast_radius'])
    if args.verbose and spn[s]['dataActions']:
      ps = list(infimum_p)
      if len(ps) == 1:
        scope, depth, impact = ps[0]
        print("  Azure Data Plane> no pairs found")
      else:
        found=False
        lca=None
        lca_depth=None
        for p in pairs:
          if p['distance']==spn[s]['blast_radius']:
            print("  Azure Data Plane> maximum pair: ",p['p1'][0],p['p2'][0])
#            if 'p2' in p:
#              print("    ",p['p2'][0])
            _,lca_depth = least_common_ancestor(hierarchy, p['p1'][0], p['p2'][0], collapsed=False, verbose=True)
            found=True
            break
  else:
    if args.live:
      with open('groups_roles.json','w') as file:
        json.dump(groups,file)
      with open('membership.json','w') as file:
        json.dump(membership,file)
      with open('gperms.json','w') as file:
        json.dump(gperms,file)
      with open('spnperms.json','w') as file:
        json.dump(spn,file)
    scores2csv(spn) 

def az_ad_sp(token=None):
  print("retrieving all your SPNs from Entra... Please be patient, il will take a few minutes")
  if not token:
    token = get_token('graph.microsoft.com')
  url = 'https://graph.microsoft.com/v1.0/servicePrincipals'  
  headers = {
    'Authorization': f'Bearer {token}',
  }
  params = {
    '$top': 999
  }
  all_sps = []
  while url:
    resp = requests.get(url, headers=headers, params=params)
    resp.raise_for_status()
    data = resp.json()
    all_sps.extend(data.get('value', []))
    url = data.get('@odata.nextLink')
    params = None
  with open('az_ad_sp.json', 'w') as file:
    json.dump(all_sps, file, indent=2)

def generate_spns_cache():
  az_ad_sp()
  if os.path.exists('az_ad_sp.json'):
    with open('az_ad_sp.json', 'r') as file:
      data = json.load(file)
    print(len(data),"SPNs found in Entra")
  else:
    print("ERROR: please load SPNs from Entra by running az_ad_sp first")
    sys.exit()
  for entry in data:
   spnscache[entry["id"]]={}
   spnscache[entry["id"]]["servicePrincipalType"]=entry["servicePrincipalType"]
   spnscache[entry["id"]]["displayName"]=entry["displayName"]
  with open('spns_cache.json', 'w') as file:
    json.dump(spnscache, file, indent=2)

def scores2csv(data):
  for d in data:
    data[d]['pid']=d
  csv_file = f"sorted_NHIs_{current_timestamp}.csv"
  headers = ["pid", "name","type","uras","memberships","WAR","blast_radius","D", "A"]
  with open(csv_file, "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(headers)
    for entry in data:
        pid = data[entry].get("pid", "")
        WAR = data[entry].get("WAR", "")
        radius = data[entry].get("blast_radius", "")
        spnType = data[entry].get("type", "")
        spnName = data[entry].get("name", "")
        URAs = data[entry].get("uras", "")
        D = data[entry].get("D", "")
        A = data[entry].get("A", "")
        groups = data[entry].get("memberships", "")
        writer.writerow([
                pid,
                spnName,
                spnType,
                URAs,
                groups,
                WAR,
                radius,
                D,
                A
        ])
  print(f"CSV file '{csv_file}' has been created successfully!")

if args.version:
  print("Azure Silhouette, a NHI sorter and minimizer")
  print("  Version 2.1 (Ultrametry edition), by Christophe Parisel (labyrinthinesecurity)")
  print("  Licensed under LGPL, use at your own risks!")
  print("  https://github.com/labyrinthinesecurity/silhouette")
  sys.exit()

if args.single and args.live==False:
  if os.path.exists('groups_roles.json'):
    with open('groups_roles.json','r') as file:
      groups=json.load(file)
  if os.path.exists('membership.json'):
    with open('membership.json','r') as file:
      membership=json.load(file)
  if os.path.exists('gperms.json'):
    with open('gperms.json','r') as file:
      gperms=json.load(file)
  if os.path.exists('management_hierarchy.csv'):
    pass
  else:
    save_hierarchy_to_csv(tenant_id,"management_hierarchy.csv")
  combined=fetch_combined(args.single)
elif args.live == False:
  if os.path.exists('groups_roles.json'):
    with open('groups_roles.json','r') as file:
      groups=json.load(file)
  if os.path.exists('membership.json'):
    with open('membership.json','r') as file:
      membership=json.load(file)
  if os.path.exists('gperms.json'):
    with open('gperms.json','r') as file:
      gperms=json.load(file)
  if os.path.exists('management_hierarchy.csv'):
    pass
  else:
    save_hierarchy_to_csv(tenant_id,"management_hierarchy.csv")
  if os.path.exists('ARG.json'):
    with open('ARG.json','r') as file:
      combined=json.load(file)
  else:
    combined=fetch_combined(args.single)
else:
  save_hierarchy_to_csv(tenant_id,"management_hierarchy.csv")
  combined=fetch_combined(args.single)

hierarchy = load_hierarchy_from_csv("management_hierarchy.csv")
shunts = {}
shunts['native']= hierarchy
for f in os.listdir("."):
  if f.startswith("shunt_") and f.endswith(".csv"):
    shunts[f[6:-4]] = pd.read_csv(f)

if args.single:
  args.apps=False
  args.mis=False
  generate_WAR_norms(args.single,combined)
else:
  if args.live==True:
    generate_spns_cache()
  generate_WAR_norms(args.single,None)
