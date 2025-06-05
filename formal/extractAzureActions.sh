#!/usr/bin/bash
#az provider operation list > azrp.json
jq -r '.. | select(.isDataAction? and .name? and (.name | contains("/"))) | "\((.id // "") | sub(".*/"; ""))/\(.name)"' azrp.json | sort -u > azureDataActions.txt
sed -i 's/^.//' azureDataActions.txt
jq -r '.. | select(.name? and (.name | contains("/")) and (.isDataAction? | not) and (.name | test("^Microsoft\\.[^/]+/[^/]+(/[^/]+)*$"))) | "\((.id // "") | sub(".*/"; ""))/\(.name)"' azrp.json | sort -u > azureActions.txt
sed -i 's/^.//' azureActions.txt
