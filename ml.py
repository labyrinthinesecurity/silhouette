#!/usr/bin/python3

import pandas as pd
from datetime import datetime
from sklearn.cluster import KMeans
from sklearn.preprocessing import OneHotEncoder
from sklearn.compose import ColumnTransformer
from sklearn.metrics import silhouette_score
from sklearn.decomposition import PCA
from mpl_toolkits.mplot3d import Axes3D
import numpy as np

import seaborn as sns
import matplotlib.pyplot as plt
import sys,random,os

partition=os.getenv('ingest_partition')

np.random.seed(42)
#centroids=np.loadtxt('t0_centroids.csv',delimiter=',')
dstamp=datetime.now().strftime("%y%m%d")
print("Todays date timesamp is:",dstamp)

data0 = pd.read_csv(f"{partition}_output.csv")
data = data0.drop('Name',axis=1)
columns_to_drop = [col for col in data0.columns if col != 'Name']
data1 = data0.drop(columns=columns_to_drop, axis=1)
#print(data1.head())

# Selecting features for one-hot encoding
categorical_features = ['SWAR', 'GWAR', 'SSResolution', 'SWResolution', 'SAResolution', 'GWResolution', 'GAResolution']
one_hot = OneHotEncoder()
transformer = ColumnTransformer([("one_hot", one_hot, categorical_features)], remainder='passthrough')

# Apply one-hot encoding
transformed_data = transformer.fit_transform(data)
transformed_data = pd.DataFrame(transformed_data, columns=transformer.get_feature_names_out())

silhouette_scores = []
max_silhouette=0.0
max_silhouette_index=0
for k in range(20, 40):  # Silhouette score cannot be computed for a single cluster
    model = KMeans(n_clusters=k,random_state=42)
    model.fit(transformed_data)
    labels = model.labels_
    score=silhouette_score(transformed_data, labels)
    if score>max_silhouette:
      max_silhouette=score
      max_silhouette_index=k
    silhouette_scores.append(score)
print(silhouette_scores)
print(max_silhouette,max_silhouette_index)

k =  max_silhouette_index
#kmeans = KMeans(n_clusters=k,init=centroids,random_state=42)
kmeans = KMeans(n_clusters=k,random_state=42)
kmeans.fit(transformed_data)

#data1['labels'] = kmeans.labels_
cluster_centers = kmeans.cluster_centers_
np.savetxt(f"t{dstamp}_centroids.csv",cluster_centers,delimiter=',')

# Add the cluster labels to the dataset
data['cluster'] = kmeans.labels_

result = data1.merge(data,left_index=True,right_index=True)
# place first column and label at the end
first_column = result.pop('Name') 
result['Name'] = first_column      

columns_to_drop.append('cluster')
#print(columns_to_drop)

result_dict=result.groupby('cluster').apply(lambda x: x.drop(columns_to_drop,axis=1).to_dict('records')).to_dict()
import json
with open(f"{partition}_clusterized.json",'w') as file:
  json.dump(result_dict,file,indent=2)

#results = []
#for i in range(0,k):
#  rz=result[result['cluster']==i]
#  results.append(rz)
#  print(rz.head())
#  cluster=str(i)
#  rz.to_csv(f"cluster_{cluster}.csv", index=False)
