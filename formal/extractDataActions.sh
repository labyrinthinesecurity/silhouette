#!/usr/bin/bash
jq -r '
  to_entries[]
  | .value.dataActions_dict
  | to_entries[]
  | .value[]
' spnperms.json | sort -u > dataActions.txt

jq -r '
  to_entries[]
  | .value.actions_dict
  | to_entries[]
  | .value[]
' spnperms.json | sort -u > actions.txt

