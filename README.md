# Azure Silhouette, a SPN sorter and roles minimizer

<div align="center">
<img src="https://github.com/labyrinthinesecurity/silhouette/blob/2.1/silhouette_logo_ultrametry.png" width="50%">
</div>

## Introduction

Silhouette is a **Non Human Identities (NHI) sorter and roles minimizer** which runs through all your Azure SPNs and gives them two scores according to their RBAC permissions and scopes:
- a score in the Control Plane,
- a score in the Data Plane

The higher the scores, the more powerful the SPN.

Direct role assignements are taken into account as well as indirect assignments through group membership.

Sorting silhouette by control plane or data plane score is very useful to prepare for a NHI de-escalation plan. It can also be used to monitor NHIs lifecycles (create/delete NHIs, change in their permissions)

Control Plane scores are generated with the help of a new norm called the *WAR norm*, and a new metric called the *WAR distance*. The WAR metric calculates the distance of each cluster to the origin. The distance ranges from 0 (cluster has no rights at all) at the origin to 999 (cluster is Tenant admin). Mathematical metrics obey a strict hierarchy which allows to make accurate distance measurements between cluster permissions. 

Data Plane scores are generated with the help of a new distance called the *blast radius*. It ranges from 0 (no data actions) to 1.0 (tenantwide lateral motion). The blast radius captures the maximum breadth of a data leakage or a data forgery.

In the data plane, you may also calculate the *data perimeter* of your NHIs. It provides a high resolution contour of your SPN's data action, complementing the blast radius nicely in advanced prioritization scenarios.

<div align="center">
<img src="https://github.com/labyrinthinesecurity/silhouette/blob/2.1/rbac_distance.jpeg" width="50%">
</div>

## Pre-requisites
- Python 3.6 or later

## Configure
You need to have access to an auditor SPN with tenant-wide read only permissions in Azure, and the ability to list and get SPNs details from Entra ID

Then, set 3 environment variables and you're good to go!
```
ARM_TENANT_ID: your Tenant ID
ARM_CLIENT_ID: the ID of your auditor SPN
ARM_CLIENT_SECRET: the password of your auditor SPN
```

## Run
To sort your SPNs, run ***silhouette.py*** without options. It will generate *sorted_NHIs.csv* in the local directory. This CSV file will contain all SPN IDs having 'actions' or 'data actions' permissions in your Tenant, along with their associated scores and other useful statistics:
- *pid*, the SPN principalID
- *name*, display name (if any)
- *type*, typically Application or ManagedIdentity for NHIs
- *uras*, number of unique Azure RBAC roles assigned to this SPN at a given level (Tenant, resource group, ...)
- *memberships*, number of Entra groups bearing RBAC roles this SPN belongs to (including nested groups)
- *WAR*, the control plane score, in descending order
- *blast radius*, the data plane score, in descending order
- *D*, a boolean identifying whether the SPN can define roles
- *A*, a boolean identifying whether the SPN can make role assignements

WARNING: scanning a large number of SPNs and their groups membership takes a long time, so silhouette.py throttles the number of API calls it makes against Azure. ***Expect the sorting to take at least 2 hours per 10000 SPNs***

### Sample output
Here is what a typical WAR scoring will look like in *sorted_NHIs.csv*:

```
pid,name,type,uras,memberships,WAR,blast_radius,D,A
0345bdae-8b38-443a-ac91-5c414982b422,my_UAMI,ManagedIdentity,2,0,888,0.0,False,False
d8232080-383c-49cf-9858-29d2ad40e9bf,some_spn_name,Application,5,0,607,0.25,False,False
491ed9ca-3339-44e5-b9ad-971a0380d632,another_spn,ManagedIdentity,7,3,449,0.125,False,False
c5fcf174-6472-46ad-b822-613680c33060,app_spn,Application,3,9,24,0.0,False,False
```

### Advanced options

silhouette.py supports the following command line options, detailed thereafter:
```
--single          generate WAR score and statistics for a single SPN
--live            refresh local Silhouette caches (slow, but accurate)
--apps            ignore Managed Identities
--mis             ignore Applications 
--verbose         produce rich stdout logs for troubleshooting and/or checking progress
```

#### --single option
Rather than producing a CSV file, the *--single* option dumps statistics of a single SPN to standard output:
```
silhouette.py --single f88b148f-5e7d-4b6a-a9a9-08d1911b1fe2
  unique role assignments: 121
  group memberships: 4

  Azure Control Plane> WAR norm: 172
  Entra Control Plane> can assign roles: False
  Entra Control Plane> can define roles: True

  Azure Data Plane> blast radius: 0.0625
```

#### Caching options
By default, SPN IDs, roles and groups are persisted in several local files that you don't need to know about but tha we reference for your information:
- *az_ad_sp.json*, a dump of all your Tenant's SPNs (output of az ad sp)
- *ARG.json*, a dump of Azure roles from Azure Resource Explorer
- *groups_roles.json*, a dump of groups and their RBAC roles
- *membership.json*, a dump of group memberships
- *gperms.json*, a dump of fine grained RBAC permissions
- *management_hierarchy.csv*, a dump of the clustering structure of all management groups and subscriptions in your Tenant
- *spnperms.json*, a dump of SPN properties used for calculating scores

This makes subsequent runs much faster, but subsequent runs won't pull any updates from Azure (roles definitions and assignments, fine grained permissions) and Entra (principals, groups, memberships)
To prevent drift and to keep silhouette in sync with your actual live configuration, you should refresh these files by explicitely setting the *--live* option

## Understanding Silhouette scores

### Control plane scores
The WAR norm doesn't measure IAM management permissions (i.e. the capability to define or assign roles). This latter capability is measured by the DA norm, which is not implemented in Silhouette.

Concretely, this means that the following IAM permissions are being ignored by the WAR norm:
- microsoft.authorization/roleassignments
- microsoft.authorization/roledefinitions
- microsoft.authorization/denyassignments
- microsoft.authorization/elevateaccess
- microsoft.authorization/classicadministrators
- microsoft.authorization/roleeligibilityschedule
- microsoft.authorization/rolemanagement*
- microsoft.managedidentity/assign/action
- microsoft.managedidentity/*/assign/action

#### Examples
Here are a few examples of silhouette configurations based on the WAR norm table shown below (by decreasing order of privileges):
- 999 corresponds to Tenant admin
- 888 corresponds to management group level superadmin
- 777 corresponds to subscription level superadmin
- 477 corresponds to subscription level for W, A and R
- 466 corresponds to subscription level for W, resource group level for A and R
- 377 corresponds to resource group level for W, subscription level for A and R 
- 367 corresponds to resource group level for W and A, subscription level for R
- 346 corresponds to resource group level for W and R, resource level for A
- 026 corresponds to subresource level for A, resource group level for R, and no W action
- 000 corresponds to no control plane rights (except IAM roles management, as explained above)

<div align="center">
<img src="https://github.com/labyrinthinesecurity/silhouette/blob/2.1/WARnormTable.PNG">
</div>

### Data plane scores
The blast radius leverages the native clustering hierarchy of resources management in Azure to compute an ultrametric distance between any two pairs of resources a SPN is assigned dataActions.
The ultrametric maximum represents the largest lateral motion a SPN can perform across your data plane, hence its name: blast radius. This is useful to assess the extent of potential data leakages or data forgeries.

<div align="center">
<img src="https://github.com/labyrinthinesecurity/silhouette/blob/2.1/blast_radius.png" width="70%">
</div>

#### Example

Consider the resources depicted in green in the image below: these are a storage account and a cosmosDB instance.

<div align="center">
<img src="https://github.com/labyrinthinesecurity/silhouette/blob/2.1/blast_radius_example.png" width="50%">
</div>

Their Least Common Ancestor (LCA) in Azure's Tenant hierarchy is the Tenant itself. The "raw" ultrametric distance between two points is 1/(2^LCA), so their distance is 1/2^0 = 1.0

A distance of 1.0 is maximal, corresponding to a Tenant-wide lateral motion

#### Calculation details
Under the hood, Silhouette performs a more advanced calculation: depending on the dataAction, the "raw" ultrametric distance is modified by a factor called the impact: 

- a SPN with '*' data action or with both 'Read' and 'Write' data actions has an impact of 2
- a SPN with either a 'Read' or a 'Write' data action (but not both) has an impact of 1. 
- if the data action is 'Action', then the impact is 0, meaning Actions are basically ignored.


To cater for this impact factor, the actual ultrametric is: impact/(2^(2*LCA+1))

- if impact=2, then we measure a distance of 2/(2^(2*LCA+1))=1/(2^(2*LCA)). 
- if impact=1, then the measurement is 1/(2^(2*LCA+1))

Therefore we make sure that, for any given pair of data actions, their distance falls within interval [ 1/(2^(2*LCA+1)), 1/(2^(2*LCA)) ] which is not overlapping with LCA+1 and LCA-1. The full ordering of pairs is preserved!

Check my Blast Radius preprint for full details: [arxiv Blast Radius](https://arxiv.org/abs/2504.13747)

#### Blast radius computation option
By default, the blast radius only relies on Azure's native Tenant hierarchy. But you may want to design alternate hierarchies which better reflect the organization of your Coporation and to get "tighter" blast radii. 
This can be useful is some management group is undergoing a migration, following a reorganization, a merger, a carve-out, etc.

Each alternate hierarchy must be described in a "shunt" file, called shunt_{hierarchy_name}.csv

To start experimentating with alternate hierarchies, simply copy the native hierarchy called management_hierarchy.csv to shunt_test.csv, add or modify a child/parent relationship and run silhouette with your usual options

### Data perimeter
Once you have run silhouette successfully across your Tenant, you may calculate the data perimeter of all your SPNs using the *dataPerimeter.py* script to discriminate further between SPNs having the same Blast radius. It will dump a CSV containing the pid of each SPN, their blast radius, the count of data actions, the data perimeter and the mean ultrametric distance between data actions.

```
pid;blast_radius;data_actions;data_perimeter;mean
b17efda0-13fa-47d7-9272-4ecef0381547;0.000244140625;13;0.0005035400390625;0.0001678466796875
e8878def-d88d-4e1f-b44c-886452a6d45b;0.0625;7;0.12514540553092957;0.009043391793966293
```

Check my data perimeter preprint for full details: [arxiv Data Perimeter](https://arxiv.org/abs/2505.13238)
