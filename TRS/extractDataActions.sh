#!/usr/bin/bash
jq -r '
  to_entries[]
  | .value.dataActions_dict
  | to_entries[]
  | .value[]
' spnperms.json | sort -u > dataActions.txt

