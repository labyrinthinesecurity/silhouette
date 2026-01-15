#!/usr/bin/python3
"""
Azure Silhouette - A Non-Human Identity (NHI) Risk Analyzer

This tool analyzes Azure service principals (SPNs) and managed identities to quantify
their security risk based on assigned RBAC permissions. It calculates WAR (Write/Action/Read)
scores and blast radius metrics to help identify over-privileged identities.

Key Features:
- WAR Score Calculation: Quantifies Azure control plane permissions across scope levels
- Blast Radius Analysis: Measures data plane permission impact using ultrametry
- Group Membership Resolution: Includes inherited permissions from Azure AD groups
- Define/Assign Detection: Identifies identities that can modify RBAC
- Export to CSV: Generates ranked lists for remediation prioritization

Usage:
    python silhouette.py                    # Analyze all SPNs (uses cache)
    python silhouette.py --live             # Refresh cache and analyze
    python silhouette.py --single <SPN_ID>  # Analyze specific SPN
    python silhouette.py --frs              # Generate fibration data

Author: Christophe Parisel (labyrinthinesecurity)
License: LGPL
Version: 2.1 (Ultrametry edition)
"""
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
parser.add_argument('--frs', required=False, action="store_true", help='preprocessing for fibration')
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
strict_frs={}
groups={}
hierarchy = None

# WAR Scoring Matrix: Maps permission types and scope levels to numerical scores
# Higher scores indicate greater risk. Scores are combined (Write + Action + Read) to create
# a composite WAR score that quantifies an identity's effective Azure permissions.
# Scope levels: 0=none, 1=tenant, 2=mgmt group, 3=subscription, 4=resource group, 6=resource, 8=subresource
silhouette={
        'superadmin': {
            '0': 0,     # none - no permissions
            '1': 900,   # tenant - highest risk (full tenant control)
            '2': 800,   # mgmt group - very high risk (multiple subscriptions)
            '3': 700,   # subscription - high risk (subscription-wide access)
            '4': 300,   # resource group - medium risk (RG-scoped)
            '6': 200,   # resource - lower risk (single resource)
            '8': 100,   # subresource - lowest risk (subresource only)
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
    """
    Classify permissions related to Define/Assign (DA) capabilities in Azure.

    This function analyzes Azure permissions to determine if they grant capabilities to
    define custom roles or assign roles to principals. It specifically looks for permissions
    related to microsoft.authorization and microsoft.managedidentity.

    Args:
        permission: Azure permission string (e.g., "Microsoft.Authorization/roleDefinitions/write")
        notlowperms: List of lowercase permission strings that are explicitly excluded
        notsegments: List of permission segments split by "/" for exclusion checking

    Returns:
        str or None: Classification result - one of:
            - "superadmin": Full administrative permissions including both define and assign
            - "define": Can define custom roles but not assign them
            - "assign": Can assign roles but not define custom roles
            - None: Permission does not grant define or assign capabilities
    """
    lowperm = permission.lower()
    segments = lowperm.split("/")

    assigner=False
    designer=False

    if notlowperms and (("microsoft.authorization/" in notlowperms[0]) or ("microsoft.managedidentity/" in notlowperms[0])):
        return None 
    elif ("microsoft.authorization/" not in lowperm) and ("microsoft.managedidentity/" not in lowperm):
        return None 

    if permission == "*" or permission == "/*":
        return "superadmin"

    # Check for role assignment permissions (unless explicitly excluded)
    if "microsoft.authorization/roleassignments" in lowperm:
        if not (notlowperms and "microsoft.authorization/roleassignments" in notlowperms[0]):
            assigner=True

    # Check for role definition permissions (unless explicitly excluded)
    if "microsoft.authorization/roledefinitions" in lowperm:
        if not (notlowperms and "microsoft.authorization/roledefinitions" in notlowperms[0]):
            designer=True

    # Check for managed identity assignment permissions (unless explicitly excluded)
    if "/assign/action" in lowperm:
        if "microsoft.managedidentity/" in lowperm:
            if not (notlowperms and "/assign/action" in notlowperms[1]):
                assigner=True
        else:
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

    if segments[-1]=="*":
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
    """
    Classify an Azure permission based on its Write/Action/Read (WAR) characteristics.

    This function categorizes Azure RBAC permissions into a hierarchy of access levels:
    superadmin, write/delete, action, read, or none/unknown. The classification considers
    both the permission scope and the operation type.

    Args:
        permission: Azure permission string (e.g., "Microsoft.Compute/virtualMachines/write")
        resolution: Scope resolution level (1=tenant, 2=management group, 3=subscription,
                   4=resource group, 6=resource, 8=subresource)
        verbose: Boolean flag to enable logging of permission classifications

    Returns:
        tuple: (classification, resource_provider) where:
            - classification: One of "superadmin", "write/delete", "action", "read", "none", "unknown"
            - resource_provider: The Azure resource provider (first segment) or None for wildcards
    """
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

    if segments[-1]=="*":
        if verbose:
            wpd=permission+":S:"+str(resolution)
            if wpd not in warpermdict:
              warpermdict[wpd]=0
        return "superadmin",rp
    if "write" in segments[-1].lower() or "delete" in segments[-1].lower():
        if verbose:
          wpd=permission+":W:"+str(resolution)
          if wpd not in warpermdict:
            warpermdict[wpd]=0
        return "write/delete",rp
    elif "action" in segments[-1].lower():
        if verbose:
          wpd=permission+":A:"+str(resolution)
          if wpd not in warpermdict:
            warpermdict[wpd]=0
        return "action",rp
    elif "read" in segments[-1].lower():
        if verbose:
          wpd=permission+":R:"+str(resolution)
          if wpd not in warpermdict:
            warpermdict[wpd]=0
        return "read",rp
    if verbose:
      wpd=permission+":U:"+str(resolution)
      if wpd not in warpermdict:
        warpermdict[wpd]=0
    return "unknown",None



def partition_permissions(permissions,notpermissions,resolution):
    """
    Partition a list of permissions into WAR (Write/Action/Read) and DA (Define/Assign) categories.

    This function processes a set of Azure permissions and classifies each one into both
    WAR categories (for resource access) and DA categories (for role management capabilities).
    Excluded permissions (notpermissions) are considered during classification.

    Args:
        permissions: List of Azure permission strings to classify
        notpermissions: List of permission strings that are explicitly excluded
        resolution: Scope resolution level for WAR classification

    Returns:
        tuple: (war_perms, da_perms) where:
            - war_perms: Set of strings formatted as "classification:resolution:permission"
            - da_perms: Set of strings formatted as "classification:permission"
    """
    war_perms=set()
    da_perms=set()
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

def _calculate_resolution_scores(resource_resolution):
    """
    Calculate resolution scores for a given resource hierarchy level.

    Maps Azure resource resolution levels to two different scoring systems:
    - General resolution (r): Coarse-grained grouping (0=tenant/MG, 1=sub/RG, 2=resource/subresource)
    - Strict resolution (ka): Fine-grained hierarchy (0=tenant, 1=MG, 2=sub, 3=RG, 4=resource, 5=subresource)

    Args:
        resource_resolution: Integer representing the Azure resource hierarchy level
            (1=tenant, 2=MG, 3=subscription, 4=RG, 6=resource, 8=subresource)

    Returns:
        tuple: (r, ka) where:
            - r: General resolution score (0-2)
            - ka: Strict resolution score (0-5)
    """
    # General resolution: groups similar scopes together
    if resource_resolution >= 5:  # resource or subresource
        r = 2
    elif resource_resolution >= 3:  # subscription or resource group
        r = 1
    else:  # tenant or management group
        r = 0

    # Strict resolution: maintains full hierarchy granularity
    if resource_resolution == 1:  # tenant
        ka = 0
    elif resource_resolution == 2:  # management group
        ka = 1
    elif resource_resolution == 3:  # subscription
        ka = 2
    elif resource_resolution == 4:  # resource group
        ka = 3
    elif resource_resolution == 6:  # resource
        ka = 4
    else:  # subresource (8)
        ka = 5

    return r, ka


def _initialize_group_dict():
    """
    Initialize an empty group permissions dictionary with all required fields.

    Creates a standardized data structure for storing group permission information
    including role assignments, permission sets, WAR scores, and data actions.

    Args:
        None

    Returns:
        dict: Initialized group dictionary with empty/default values for all fields
    """
    return {
        'war_permset': [],
        'da_permset': [],
        'golden_counts': {},
        'dataActions': False,
        'dataActions_dict': {},
        'actions_dict': {},
        'rdids': [],
        'resolutions': [],
        'strict_resolutions': [],
        'WAR': 0,
        'D': False,
        'A': False
    }


def _initialize_spn_dict():
    """
    Initialize an empty service principal permissions dictionary with all required fields.

    Creates a standardized data structure for storing SPN permission information
    including role assignments, group memberships, permission sets, WAR scores, and data actions.

    Args:
        None

    Returns:
        dict: Initialized SPN dictionary with empty/default values for all fields
    """
    return {
        'war_permset': [],
        'da_permset': [],
        'golden_counts': {},
        'memberships': None,
        'groups': [],
        'uras': 0,
        'iras': 0,
        'WAR': 0,
        'A': False,
        'D': False,
        'dataActions': False,
        'dataActions_dict': {},
        'actions_dict': {},
        'rdids': [],
        'resolutions': [],
        'strict_resolutions': [],
        'minW': 0,
        'minA': 0,
        'minR': 0
    }


def extract_azure_resource_details(s):
    """
    Extract Azure resource hierarchy details from a resource scope string.

    Parses an Azure resource scope (e.g., role assignment scope) to extract information
    about the resource hierarchy level and components. Recognizes different scope levels
    from root ('/') down to subresources.

    Args:
        s: Azure resource scope string (e.g., '/subscriptions/xxx/resourcegroups/yyy/...')

    Returns:
        tuple: (details_tuple, resolution_level) where:
            - details_tuple: 9-element tuple containing (tenant, mgmt_group, subscription,
                           resource_group, provider, type, name, subtype, subname)
            - resolution_level: Integer representing scope hierarchy:
                1 = Root/Tenant level
                2 = Management Group
                3 = Subscription
                4 = Resource Group
                6 = Resource
                8 = Subresource
                None = Unrecognized format
    """
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
  """
  Probe the number of role assignments for a specific Azure AD group.

  Queries Azure Resource Graph to count how many role assignments exist for
  a given group ID. Used to determine if a group has Azure RBAC permissions
  before fetching detailed permission data.

  Args:
      gid: Azure AD group ID (GUID)
      gtoken: Azure Resource Graph API token (refreshed if needed)

  Returns:
      tuple: (count, updated_token) where:
          - count: Number of role assignments for the group
          - updated_token: Refreshed API token
  """
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
  """
  Fetch detailed role assignments and permissions for an Azure AD group.

  Queries Azure Resource Graph to retrieve all role assignments for a group,
  including role definitions with their actions, notActions, dataActions, and
  notDataActions. This provides complete permission details for group-based access.

  Args:
      gid: Azure AD group ID (GUID)
      gtoken: Azure Resource Graph API token (refreshed if needed)
      current: Current progress counter (for display)
      total: Total number of groups to process (for display)

  Returns:
      tuple: (results, updated_token) where:
          - results: List of combined role assignment and definition data
          - updated_token: Refreshed API token
  """
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
  """
  Fetch combined role assignment and definition data for service principals.

  Queries Azure Resource Graph to retrieve role assignments for service principals,
  joining with role definitions to get complete permission details. Can fetch for
  a single SPN (when pid provided) or all SPNs (when pid is None).

  Args:
      pid: Service principal ID (GUID) to fetch, or None to fetch all SPNs

  Returns:
      list or None: When pid is provided, returns list of role data for that SPN.
                    When pid is None, saves all data to ARG.json and returns None.
  """
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
  """
  Calculate the WAR (Write/Action/Read) score for an identity.

  Computes a numerical score representing an identity's Azure RBAC permissions
  based on write/delete, action, and read capabilities across different scope levels.
  The score uses the silhouette scoring matrix which weights permissions based on
  scope (tenant/subscription/resource/etc) and operation type.

  Args:
      identity: Dictionary containing identity data with 'war_permset', 'da_permset',
               and 'golden_counts' keys
      minW: Minimum write score (from inherited group permissions)
      minA: Minimum action score (from inherited group permissions)
      minR: Minimum read score (from inherited group permissions)

  Returns:
      None (modifies identity dictionary in-place, setting 'WAR', 'A', and 'D' fields)
          - identity['WAR']: Combined WAR score (write + action + read)
          - identity['A']: Boolean, can assign roles
          - identity['D']: Boolean, can define roles
  """
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
  """
  Generate WAR (Write/Action/Read) norms and blast radius scores for Azure service principals.

  This is the main analysis function that processes all service principals in the tenant,
  calculating their effective permissions including both direct role assignments and
  inherited permissions from group memberships. It computes WAR scores, identifies
  Define/Assign capabilities, and calculates blast radius for data plane permissions.

  The function handles three operational modes:
  1. Single SPN analysis (when 'single' is provided) - displays detailed stats for one SPN
  2. Full tenant analysis with live data (when args.live=True) - fetches fresh data
  3. Cached analysis (default) - uses previously cached data for faster processing

  Args:
      single: Service principal ID for single-SPN analysis, or None for full tenant scan
      combined: Pre-fetched role data when analyzing a single SPN, or None

  Returns:
      None (outputs results to console and CSV files)
          - For single SPN: prints detailed permission analysis
          - For full scan: generates sorted_NHIs_<date>.csv with all SPNs ranked by risk
          - When args.frs=True: generates FRS (Fibration) CSV files
  """
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
  roles=set()
  for role in bulk:
    roles.add(role['pid'])
  roles2=set()
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
      groupsof=set()
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
            groups[ag['id']] = _initialize_group_dict()
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
        spn[role['pid']] = _initialize_spn_dict()
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
        groupsof=set()
        rdids=[]
        resolutions=[]
        strict_resolutions=[]
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
            groups[ag['id']] = _initialize_group_dict()
            resolution=8
            for gr in g:
              for combined in gr['set_combinedRole']:
                _,rrr=extract_azure_resource_details(combined['scope'])
                r, ka = _calculate_resolution_scores(rrr)
                rdid=combined['rdid'].split('RoleDefinitions/')
                cnt=-1
                if rdid[1] in rdids:
                  for rdd in rdids:
                    cnt+=1
                    if rdd==rdid[1]:
                      break
                  if r<resolutions[cnt]:
                    resolutions[cnt]=min(r,resolutions[cnt])
                  if ka<strict_resolutions[cnt]:
                    strict_resolutions[cnt]=min(ka,strict_resolutions[cnt])
                else:
                  rdids.append(rdid[1])
                  resolutions.append(r)
                  strict_resolutions.append(ka)
                if rdid[1] not in groups[ag['id']]['rdids']:
                  groups[ag['id']]['rdids'].append(rdid[1])
                  groups[ag['id']]['resolutions'].append(r)
                  groups[ag['id']]['strict_resolutions'].append(ka)
                else:
                  cnt=-1
                  for rdd in groups[ag['id']]['rdids']:
                    cnt+=1
                    if rdd==rdid[1]:
                      break
                  if r<groups[ag['id']]['resolutions'][cnt]:
                    groups[ag['id']]['resolutions'][cnt]=min(r,groups[ag['id']]['resolutions'][cnt])
                  if ka<groups[ag['id']]['strict_resolutions'][cnt]:
                    groups[ag['id']]['strict_resolutions'][cnt]=min(ka,groups[ag['id']]['strict_resolutions'][cnt])
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
            for rzk in groups[ag['id']]['strict_resolutions']:
              strict_resolutions.append(rzk)
        if len(groupsof)>0:
          spn[role['pid']]['memberships']=len(groupsof)
          spn[role['pid']]['groups']=list(groupsof)
          spn[role['pid']]['rdids']=rdids
          spn[role['pid']]['resolutions']=resolutions
          spn[role['pid']]['strict_resolutions']=strict_resolutions
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
        print("  ",spn[role['pid']]['resolutions']," strict:",spn[role['pid']]['strict_resolutions'])
    newrdids=set()
    for combined in role['set_combinedRole']:
      _,rrr=extract_azure_resource_details(combined['scope'])
      r, ka = _calculate_resolution_scores(rrr)
      rdid=combined['rdid'].split('RoleDefinitions/')
      if rdid[1] not in spn[role['pid']]['rdids']:
        spn[role['pid']]['rdids'].append(rdid[1])
        spn[role['pid']]['resolutions'].append(r)
        spn[role['pid']]['strict_resolutions'].append(ka)
        newrdids.add(rdid[1])
        spn[role['pid']]['uras']+=1
      else:
        cnt=-1
        for ri in spn[role['pid']]['rdids']:
          cnt+=1
          if ri==rdid[1]:
            if r<spn[role['pid']]['resolutions'][cnt]:
              spn[role['pid']]['resolutions'][cnt]=min(r,spn[role['pid']]['resolutions'][cnt])
            if ka<spn[role['pid']]['strict_resolutions'][cnt]:
              spn[role['pid']]['strict_resolutions'][cnt]=min(ka,spn[role['pid']]['strict_resolutions'][cnt])
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
        frs[s]=set()
        strict_frs[s]=set()
      if args.verbose and (args.single is None):
        print("  adding RDIDS of SPN",s,"to FRS",len(spn[s]['rdids']))
      cnt=-1
      for rd in spn[s]['rdids']:
        cnt+=1
        rdscope=rd+":"+str(spn[s]['resolutions'][cnt])
        strict_rdscope=rd+":"+str(spn[s]['strict_resolutions'][cnt])
        frs[s].add(rdscope)
        strict_frs[s].add(strict_rdscope)
      if args.verbose and (args.single is None):
        print("  resulting FRS for SPN",s,"is",frs[s])
  for sd in spn_to_delete:
    del(spn[sd])
  if args.frs:
    headers = ["pid", "rdid"]
    with open(f"AZURE_FRS_{current_timestamp}.csv", "w", newline="") as f:
      writer = csv.writer(f)
      writer.writerow(headers)
      for f in frs:
        for r in frs[f]:
          row=[f,r]
          writer.writerow(row)
    with open(f"STRICT_AZURE_FRS_{current_timestamp}.csv", "w", newline="") as f:
      writer = csv.writer(f)
      writer.writerow(headers)
      for f in strict_frs:
        for r in strict_frs[f]:
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
  """
  Retrieve all service principals from Azure Entra ID (formerly Azure AD).

  Fetches a complete list of all service principals in the tenant using Microsoft Graph API.
  Handles pagination automatically to retrieve all SPNs regardless of tenant size.
  Results are saved to 'az_ad_sp.json' for caching.

  Args:
      token: Microsoft Graph API token, or None to generate a new one

  Returns:
      None (saves results to az_ad_sp.json file)
  """
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
  """
  Generate a cached lookup table of service principal metadata.

  Fetches all service principals from Entra ID and creates a streamlined cache
  containing only the essential metadata (ID, type, displayName) for faster lookups
  during WAR analysis. Results are saved to 'spns_cache.json'.

  Args:
      None

  Returns:
      None (saves results to spns_cache.json file)
  """
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
  """
  Export service principal risk scores to CSV format.

  Converts the analyzed SPN data into a CSV file with risk metrics including
  WAR scores, blast radius, role assignment counts, and Define/Assign capabilities.
  Output file is named 'sorted_NHIs_<timestamp>.csv'.

  Args:
      data: Dictionary of service principal data keyed by SPN ID, where each
            entry contains risk metrics (WAR, blast_radius, type, name, etc.)

  Returns:
      None (creates CSV file and prints confirmation message)
  """
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
