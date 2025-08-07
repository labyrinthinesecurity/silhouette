import os,requests,sys,re
import json,urllib.request
import logging,time,uuid
import pandas as pd
from datetime import datetime,timedelta
import functools,csv
from itertools import combinations
from native import get_token
import seaborn as sns
import matplotlib.pyplot as plt
import numpy as np

BIGINT=28

current_date = datetime.now()
current_timestamp = timestamp = current_date.strftime("%Y-%m-%d")

print = functools.partial(print, flush=True)    # forces flush=True for all print() calls

visited = set()
edges = []

def get_descendants(group_id,token):
    if not token:
      token = get_token('management.azure.com')
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
    url = f"https://management.azure.com/providers/Microsoft.Management/managementGroups/{group_id}/descendants?api-version=2020-05-01"
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    time.sleep(0.3)
    return response.json().get("value", [])

def create_service_group(new_group_id,parent_group_id,token):
    if not token:
      token = get_token('management.azure.com')
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
    body = {
    "kind":"ultrametry",
    "properties": {
        "displayName": new_group_id,
        "parent": {
            "resourceId": parent_group_id
                  }
        }
    }
    url = f"https://management.azure.com/providers/Microsoft.Management/serviceGroups/{new_group_id}?api-version=2024-04-01-preview"
    response = requests.put(url, headers=headers, json=body)
    response.raise_for_status()
    time.sleep(0.3)
    return response.json().get("value", [])

def move_service_group(group_id,new_parent_group_id,token):
    if not token:
      token = get_token('management.azure.com')
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
    body = {
    "kind":"ultrametry",
    "properties": {
        "displayName": group_id,
        "parent": {
            "resourceId": new_parent_group_id
                  }
        }
    }
    url = f"https://management.azure.com/providers/Microsoft.Management/serviceGroups/{group_id}?api-version=2024-04-01-preview"
    response = requests.patch(url, headers=headers, json=body)
    response.raise_for_status()
    time.sleep(0.3)
    return response.json().get("value", [])

def delete_service_group(group_id,token):
    if not token:
      token = get_token('management.azure.com')
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
    url = f"https://management.azure.com/providers/Microsoft.Management/serviceGroups/{group_id}?api-version=2024-04-01-preview"
    response = requests.delete(url, headers=headers)
    response.raise_for_status()
    time.sleep(0.3)
    return response.json().get("value", [])

def ancestors_service_group(group_id,token):
    if not token:
      token = get_token('management.azure.com')
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
    all_items = []
    url = f"https://management.azure.com/providers/Microsoft.Management/serviceGroups/{group_id}/listAncestors?api-version=2024-04-01-preview"
    response = requests.post(url, headers=headers)
    response.raise_for_status()
    data = response.json()
    all_items.extend(data.get("value", []))
    # Paginate using nextLink if it exists
    next_link = data.get("nextLink")
    while next_link:
        response = requests.get(next_link, headers=headers)
        response.raise_for_status()
        data = response.json()
        all_items.extend(data.get("value", []))
        next_link = data.get("nextLink")
        time.sleep(0.1)
    return all_items

def create_member(rel_id,group_id,token):
    if not token:
      token = get_token('management.azure.com')
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
    body = {
        "properties": {
                        "targetId": f"/providers/Microsoft.Management/serviceGroups/{group_id}"
                      }
    }
    url = f"https://management.azure.com/providers/Microsoft.Relationships/serviceGroupMember/{rel_id}?api-version=2023-09-01-preview"
    response = requests.put(url, headers=headers, json=body)
    response.raise_for_status()
    time.sleep(0.3)
    return response.json().get("value", [])

def get_member(rel_id,token):
    if not token:
      token = get_token('management.azure.com')
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
    url = f"https://management.azure.com/providers/Microsoft.Relationships/serviceGroupMember/{rel_id}?api-version=2023-09-01-preview"
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    time.sleep(0.3)
    return response.json().get("value", [])

def delete_member(rel_id,token):
    if not token:
      token = get_token('management.azure.com')
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
    url = f"https://management.azure.com/providers/Microsoft.Relationships/serviceGroupMember/{rel_id}?api-version=2023-09-01-preview"
    response = requests.delete(url, headers=headers)
    response.raise_for_status()
    time.sleep(0.3)
    return response.json().get("value", [])


def extract_child_id(resource_id):
    """
    Extracts the leaf ID from a full Azure resource ID.

    Handles:
    - /managementGroups/{groupId}
    - /subscriptions/{subscriptionId}
    """
    parts = resource_id.strip("/").split("/")
    if "subscriptions" in parts:
        return parts[parts.index("subscriptions") + 1]
    elif "managementGroups" in parts:
        return parts[parts.index("managementGroups") + 1]
    else:
        raise ValueError(f"Unrecognized resource ID format: {resource_id}")

def walk_tree(parent_id):
    if parent_id in visited:
        return
    visited.add(parent_id)
    print(f"📁 Processing: {parent_id} ...")
    descendants = get_descendants(parent_id,None)
    for desc in descendants:
        child_type = desc["type"]
        child_id = desc["name"]
        child_props = desc.get("properties", {})
        parent_info = child_props.get("parent", {})
        parent_ref = parent_info.get("id")

        if parent_ref:
            parent = extract_child_id(parent_ref)
            edges.append((child_id, parent))
            if child_type == "Microsoft.Management/managementGroups":
                walk_tree(child_id)

def save_hierarchy_to_csv(tenant_id,filename):
  edgecache={}
  walk_tree(tenant_id)
  with open(filename, mode="w", newline="") as file:
    writer = csv.writer(file)
    writer.writerow(["child", "parent"])
    for child, parent in edges:
      cacheline=str(child)+":"+str(parent)
      if cacheline not in edgecache:
        edgecache[cacheline]=1
        writer.writerow([child, parent])

def load_hierarchy_from_csv(filename):
    df = pd.read_csv(filename)
    return df

def get_resource_path(df, resource_or_scope, collapsed=False):
    """
    Returns the full path from the tenant root to the given resource or scope.
    Skips providers and resource provider namespaces properly.
    """
    resource_or_scope = normalize_scope_keywords(resource_or_scope)
    child_to_parent = dict(zip(df['child'], df['parent']))

    def trace_to_root(child_id):
        path = []
        current = child_id
        while current in child_to_parent:
            path.append(current)
            current = child_to_parent[current]
        path.append(current) 
        return list(reversed(path))

    if isinstance(resource_or_scope, tuple):
        resource_or_scope = resource_or_scope[0]

    parts = resource_or_scope.strip("/").split("/")
    path = []

    if parts == ['']:  # special case: "/"
        return ["TENANT_ROOT"]

    if "subscriptions" in parts:
        sub_idx = parts.index("subscriptions")
        sub_id = parts[sub_idx + 1]
        
        # Trace management group path down to subscription
        path = trace_to_root(sub_id)

        # Parse deeper (after subscription)
        i = sub_idx + 2
        while i < len(parts):
            if parts[i] == "resourcegroups":
                path.append(parts[i+1])
                i += 2
            elif parts[i] == "providers":
                # Skip "providers" and the provider namespace (e.g., "Microsoft.Storage")
                i += 2
            else:
                if collapsed:
                    # group all the remaining resource structure
                    remaining = parts[i:]
                    if remaining:
                        path.append("/".join(remaining))
                    break
                else:
                    # add resource types/names individually
                    path.append(parts[i])
                    if i+1 < len(parts):
                        path.append(parts[i+1])
                    i += 2
    elif "managementgroups" in parts:
        mg_idx = parts.index("managementgroups")
        mg_id = parts[mg_idx + 1]
        path = trace_to_root(mg_id)
    else:
        raise ValueError(f"Unrecognized format: {resource_or_scope}")

    return path


def least_common_ancestor(df, resource_or_scope1, resource_or_scope2, collapsed=False, verbose=False):
    """
    Computes the Least Common Ancestor (LCA) of two resources or scopes.
    """
    try:
        path1 = get_resource_path(df, resource_or_scope1, collapsed)
        path2 = get_resource_path(df, resource_or_scope2, collapsed)
    except ValueError as e:
        if verbose:
            print(f"[ERROR] Resource path resolution failed: {e}")
        return None, None

    min_len = min(len(path1), len(path2))
    lca = None
    lca_depth = 0

    for i in range(min_len):
        if path1[i] == path2[i]:
            lca = path1[i]
            lca_depth = i
        else:
            break

    if verbose:
        print("📄 Path 1:")
        for i, val in enumerate(path1):
            marker = "⬅️ LCA" if i == lca_depth else ""
            print(f" {i}> {val} {marker}")

        print("\n📄 Path 2:")
        for i, val in enumerate(path2):
            marker = "⬅️ LCA" if i == lca_depth else ""
            print(f" {i}> {val} {marker}")

        print(f"\n🔗 Least Common Ancestor: {lca} (depth {lca_depth})")

    return lca, lca_depth

def ultrametric_distance(df, resource_or_scope1, resource_or_scope2, collapsed=False, verbose=False):
    """
    Computes the ultrametric distance between two resource scopes using the tenant hierarchy.

    Parameters:
    - df: The management group hierarchy dataframe.
    - resource_or_scope1: The first resource or scope string.
    - resource_or_scope2: The second resource or scope string.
    - collapsed: Whether to collapse subresource depth.
    - verbose: Verbosity flag for debugging.

    Returns:
    - Tuple (distance: float, lca_depth: int) if successful.
    - None if any of the scopes cannot be resolved in the hierarchy.
    """
    try:
        path1 = get_resource_path(df, resource_or_scope1, collapsed)
        path2 = get_resource_path(df, resource_or_scope2, collapsed)
    except ValueError as e:
        if verbose:
            print(f"[ERROR] Resource path resolution failed: {e}")
        return None, None

    _, lca_depth = least_common_ancestor(df, resource_or_scope1, resource_or_scope2, collapsed)
    if lca_depth is None:
        if verbose:
            print("[ERROR] LCA could not be determined.")
        return None, None

    distance = 1 / (2 ** (2 * lca_depth + 1))

    if verbose:
        print(f"\n📏 Ultrametric Distance: {distance:.10f} (from LCA depth {lca_depth})")

    return float(distance), lca_depth


def normalize_scope_keywords(scope_str):
    """
    Lowercases known Azure scope keywords in the path, preserving IDs.
    """
    keywords = {"subscriptions", "resourcegroups", "providers", "managementgroups"}
    parts = scope_str.strip("/").split("/")
    normalized_parts = [
        part.lower() if part.lower() in keywords else part
        for part in parts
    ]
    return "/" + "/".join(normalized_parts)

def categorize_actions(df, assigned_scope, data_action, collapsed=False):
    d = data_action.strip("/").split("/") if data_action.strip("/") else []
    path = get_resource_path(df, assigned_scope, collapsed)
    verb = d[-1] if d else ""
    verb_lower = verb.lower()
    if len(d)>0:
      rp=d[0].lower()
      if len(d)>1:
        domain=d[1].lower()
        if rp=="microsoft.insights" and domain in ["telemetry","metrics"]:
          return len(path)-1,"action"
    if verb == "*":
        action_category = "wildcard"
    elif verb_lower == "read":
        action_category = "read"
    elif verb_lower == "action":
        action_category = "action"
    else:
        action_category = "write"
    return len(path)-1, action_category


def group_permiplets_by_action_scope(df, role_dict, collapsed=False):
    """
    Given a dictionary with scopes as keys and lists of data actions as values,
    generate a set of permiplets grouped by action scope.

    Parameters:
    - role_dict: Dictionary where the keys are scopes (e.g., '/managementGroups/MGXX') and
      the values are lists of data actions.
    - collapsed: Whether to collapse or count each resource/subresource separately.

    Returns:
    - A set of permiplets (action_scope, depth, action_category) with impact classification.
    """
    permiplets = {}

    # Process each role scope and corresponding data actions
    for scope, data_actions in role_dict.items():
        for action in data_actions:
            depth, action_category = categorize_actions(df, scope, action, collapsed)
            if action_category == "action":
                continue
            permiplet = (scope, depth, action_category)

            # Group by action_scope and collect the categories
            if scope not in permiplets:
                permiplets[scope] = {"read": False, "write": False, "wildcard": False}

            # Set the respective flags based on action category
            permiplets[scope][action_category] = True
            permiplets[scope]['depth'] = depth

    # Assign impact levels ---
    result = set()
    for action_scope, categories in permiplets.items():
        impact = 0
        if categories["wildcard"] or (categories["read"] and categories["write"]):
            impact = 2
        elif categories["read"] or categories["write"]:
            impact = 1
        depth = categories["depth"] 
        result.add((action_scope, depth, impact))

    return result

def process_pairs(df, permiplets, collapsed=False):
    """
    Iterate over all unique permiplet pairs and compute their impact-weighted ultrametric distance.
    If any pair’s distance cannot be resolved (distance==None), stop and return (None, None).

    Parameters:
    - df: hierarchy DataFrame
    - permiplets: set of (actual_scope, depth, impact)
    - collapsed: pass‑through to depth/LCA routines

    Returns:
    - (blast_radius, results) where:
       • blast_radius is the maximum impact‑weighted distance, or None on failure  
       • results is list of dicts for each pair, or None on failure
    """
    ps = list(permiplets)
    # single permiplet base case
    if len(ps) == 1:
        scope, depth, impact = ps[0]
        big = float(impact) / (2 ** (2 * float(depth) + 1))
        return big, [{
            "p1": ps[0],
            "p2": None,
            "impact": impact,
            "lca depth": depth,
            "distance":  big
        }]

    blast_radius = 0.0
    results = []

    for p1, p2 in combinations(ps, 2):
        scope1, depth1, impact1 = p1
        scope2, depth2, impact2 = p2

        base_distance, lca_depth = ultrametric_distance(
            df, scope1, scope2, collapsed=collapsed, verbose=False
        )
        # bail out on unresolved scope
        if base_distance is None:
            return None, None

        # choose shallower’s impact (or higher if tie)
        if depth1 < depth2:
            sel_imp = impact1
        elif depth2 < depth1:
            sel_imp = impact2
        else:
            sel_imp = max(impact1, impact2)

        final_dist = base_distance * sel_imp
        blast_radius = max(blast_radius, final_dist)

        results.append({
            "p1": p1,
            "p2": p2,
            "impact": sel_imp,
            "lca depth": lca_depth,
            "distance": final_dist 
        })

    return blast_radius, results

def load_roles(collapsed=False):
    with open("spnperms.json", "r") as f:
        raw = json.load(f)

    role_dict= {}
    lr=len(raw)
    cnt=-1
    for pid, content in raw.items():
        cnt+=1
        permiplets = set([])
        da_dict = content.get("dataActions_dict", {})
        role_dict[pid]=da_dict
    return role_dict

def explain(shunts,pid):
  role_dict=load_roles()
  blast_radii={}
  max_pairs={}
  for shunt in shunts:
    print("HIERARCHY:",shunt)
    max_pairs[shunt]=[]
    permiplets = group_permiplets_by_action_scope(shunts[shunt],role_dict[pid], collapsed=False)
    ps = list(permiplets)
    if len(ps) == 1:
      scope, depth, impact = ps[0]
      blast_radii[shunt] = float(impact) / (2 ** (2 * float(depth) + 1))
      print("  (no pairs found)")
      print("  blast radius:",blast_radii[shunt])
    else:
      blast_radii[shunt],pairs=process_pairs(shunts[shunt],permiplets)
      print("  maximum pair:")
      lca=None
      lca_depth=None
      for p in pairs:
        if p['distance']==blast_radii[shunt]:
          print("  P1>",p['p1'][0])
          print("  P2>",p['p2'][0])
          _,lca_depth = least_common_ancestor(shunts[shunt], p['p1'][0], p['p2'][0], collapsed=False, verbose =True)
          max_pairs[shunt].append(p)
      print("  blast radius:",blast_radii[shunt])
    infimum=2.0
    infimum_h=''
  for br in blast_radii:
    if blast_radii[br]<infimum:
      infimum=blast_radii[br]
      infimum_h=br
  print("infimum blast radius:",infimum,"in",infimum_h,"hierarchy")
  print()
  for mx in max_pairs:
    print(mx)
    for p in max_pairs[mx]:
      print("  ",p)

def plot_crossplane0(input_path):
    """
    Generates a Seaborn scatter plot showing log10(WAR) vs blast_radius,
    with point sizes reflecting density and color indicating 'type'.
    Also draws a reference divide line from (0,0) where blast_radius = log10(WAR)/3.

    Parameters:
    - input_path: Path to the full_scope.csv file.
    """
    # Load data
    df = pd.read_csv(input_path)

    # Clean data
    df["WAR"] = df["WAR"].fillna(0)
    df["blast_radius"] = df["blast_radius"].fillna(0.0)
    df = df[df["type"].notnull()]

    # Compute log10(WAR)/3
    df["log10_WAR/3"] = (1 / 3) * np.log10(1.0 + df["WAR"])

    # Count duplicates at each (x, y, type) combination
    grouped = df.groupby(["log10_WAR/3", "blast_radius", "type"]).size().reset_index(name='count')

    # Count identity types
    total_count = len(df)
    app_count = (df["type"] == "Application").sum()
    mi_count = (df["type"] == "ManagedIdentity").sum()

    # Set aesthetic style
    sns.set(style="whitegrid", context="notebook")

    # Create scatter plot
    plt.figure(figsize=(16, 8))
    scatter = sns.scatterplot(
        data=grouped,
        x="log10_WAR/3",
        y="blast_radius",
        hue="type",
        size="count",               # Ball size = count of overlapping points
        sizes=(40, 300),
        edgecolor="black",
        palette="Set2",
        alpha=0.8
    )

    # Titles and labels
    plt.title("Blast Radius vs. log₁₀(WAR)/3 by Identity Type", fontsize=16)
    plt.xlabel("log₁₀(WAR)/3", fontsize=14)
    plt.ylabel("Blast Radius", fontsize=14)

    handles, labels = scatter.get_legend_handles_labels()
    plt.legend(handles=handles, title="Identity Type and Count", bbox_to_anchor=(1.05, 1), loc='upper left')

    # Add caption with counts
    caption = f"Total identities: {total_count}  |  Applications: {app_count}  |  Managed Identities: {mi_count}"
    plt.figtext(0.5, -0.05, caption, wrap=True, horizontalalignment='center', fontsize=12)

    # Finalize
    plt.tight_layout()
    plt.savefig("crossplane.png", bbox_inches='tight')
    #print(grouped[(grouped["log10_WAR/3"] < 3.0) & (grouped["blast_radius"] == 0.0)])

def plot_crossplane(input_path, jitter_strength=0.0001):
    """
    Generates a Seaborn scatter plot showing log10(WAR) vs blast_radius,
    with horizontal jitter and point sizes reflecting density.
    Displays total counts for all identities, Applications, and Managed Identities.

    Parameters:
    - input_path: Path to the full_scope.csv file.
    - jitter_strength: Standard deviation of horizontal jitter (default 0.01).
    """
    # Load data
    df = pd.read_csv(input_path)

    # Clean data
    #df = df[df["WAR"] >= 0]
    #df = df.dropna(subset=["blast_radius"])
    #df = df[df["type"].notnull()]
    df["WAR"] = df["WAR"].fillna(0)
    df["blast_radius"] = df["blast_radius"].fillna(0.0)


    # Compute log10(WAR)/3
#    df["log10_WAR/3"] = (1 / 3) * np.log10(1.0 + df["WAR"])
    df["log10_WAR/3"] = 1.6 * np.power(df["WAR"]/1000,4)
    #df=df[df['log10_WAR/3'] < df['blast_radius']]
    df['newblast'] = np.where(df['blast_radius'] != 0.0 , -np.log2(df['blast_radius']), BIGINT)
    #df["newblast"] = -np.log2(df["blast_radius"])
    #df["newblast"] = df["newblast"].replace([np.inf, -np.inf], BIGINT)
    df["newblast"] = df["newblast"].apply(lambda val: 1000 if 0 <= val <= 1 else val)
    df["newblast"] = df["newblast"].apply(lambda val: 900 if 2 <= val <= 3 else val)
    df["newblast"] = df["newblast"].apply(lambda val: 800 if 4 <= val <= 5 else val)
    df["newblast"] = df["newblast"].apply(lambda val: 700 if 6 <= val <= 7 else val)

    df["newblast"] = df["newblast"].apply(lambda val: 600 if 8 <= val <= 9 else val)
    df["newblast"] = df["newblast"].apply(lambda val: 500 if 10 <= val <= 11 else val)
    df["newblast"] = df["newblast"].apply(lambda val: 400 if 12 <= val <= 13 else val)
    df["newblast"] = df["newblast"].apply(lambda val: 300 if 14 <= val <= 15 else val)
    df["newblast"] = df["newblast"].apply(lambda val: 200 if 16 <= val <= 17 else val)
    df["newblast"] = df["newblast"].apply(lambda val: 100 if 18 <= val <= 19 else val)
    df["newblast"] = df["newblast"].apply(lambda val: 0 if 20 <= val <= BIGINT else val)

    df=df[df['WAR'] < df['newblast']]
    df=df[df['blast_radius'] > 0.0]

    # Apply horizontal jitter
    rng = np.random.default_rng(seed=42)
    df["jittered_x"] = df["log10_WAR/3"] + abs(rng.normal(0, jitter_strength, size=len(df)))

    # Count duplicates based on original values for proper size scaling
    df["WAR_bin"] = df["WAR"].round(0)
    df["blast_bin"] = df["newblast"].round(0)
    df["blaster"] = df["blast_radius"].round(8)
    grouped = df.groupby(["WAR_bin", "blast_bin", "type", "blaster"]).size().reset_index(name='count')

    # Merge count back to original dataframe
    df = pd.merge(
        df,
        grouped,
        how="left",
        left_on=["WAR_bin", "blast_bin", "blast_radius", "type"],
        right_on=["WAR_bin", "blast_bin", "blaster", "type"]
    )

    # Count identity types
    total_count = len(df)
    app_count = (df["type"] == "Application").sum()
    mi_count = (df["type"] == "ManagedIdentity").sum()

    # Set aesthetic style
    sns.set(style="whitegrid", context="notebook")

    # Create scatter plot
    plt.figure(figsize=(16, 8))
    scatter = sns.scatterplot(
        data=df,
        x="jittered_x",
        y="blast_radius",
        hue="type",
        size="count",
        sizes=(40, 300),
        edgecolor="black",
        palette="Set2",
        alpha=0.8
    )

    # Titles and labels
    plt.title("Blast Radius vs. log₁₀(WAR)/3 by Identity Type", fontsize=16)
    plt.xlabel("log₁₀(WAR)/3 (with jitter)", fontsize=14)
    plt.ylabel("Blast Radius", fontsize=14)

    # Legends
    handles, labels = scatter.get_legend_handles_labels()
    plt.legend(handles=handles, title="Type & Count", bbox_to_anchor=(1.05, 1), loc='upper left')

    # Caption with counts
    caption = f"Total identities: {total_count}  |  Applications: {app_count}  |  Managed Identities: {mi_count}"
    plt.figtext(0.5, -0.05, caption, wrap=True, horizontalalignment='center', fontsize=12)

    # Finalize
    plt.tight_layout()
    plt.savefig("newcrossplane.png", bbox_inches='tight')
    #print(grouped[(grouped["blast_bin"] >= 0.0) & (grouped["WAR_bin"] >= 0.0) ])
    print(grouped[["WAR_bin","blast_bin","blaster","count"]])
    #print(df[["WAR_bin","blast_bin","blast_radius"]])
