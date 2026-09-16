import cv2 as cv
import numpy as np
from features import extractFeatures
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
from sklearn.pipeline import Pipeline
from sklearn.tree import DecisionTreeClassifier
import joblib

PATH = 'data/testVideo.mp4' # path of sample video

cap = cv.VideoCapture(PATH) # capturing video from given PATH, 0 for webcam capture
feature_data = []

prev_grayscale_frame = None
while True:
    try:
        ret, frame = cap.read() # ret = if more frames exist, frame = (height, width, 3) np.array. follows bgr format.
        if not ret: # if no more frames exit
            print("End of frames!\n")
            break
        else:
            # Converting to grayscale, collapsing the 3 channels to 1 channel
            curr_grayscale_frame = cv.cvtColor(frame, cv.COLOR_BGR2GRAY) 
        diff, size, _ = extractFeatures(prev_grayscale_frame, curr_grayscale_frame, frame)
        feature_data.append((diff, size))
        # set previous frame to current frame
        prev_grayscale_frame = curr_grayscale_frame
    except KeyboardInterrupt:
        break;
cap.release()

X = np.array(feature_data)
scaler = StandardScaler()
scaled_features = scaler.fit_transform(X)
kmeans_model = KMeans(n_clusters=2, random_state = 0)
raw_cluster = kmeans_model.fit_predict(scaled_features)
centroid_values = kmeans_model.cluster_centers_
if centroid_values[0][0] > centroid_values[1][0]:
    critical_cluster_id = 0
else: 
    critical_cluster_id = 1
y = (raw_cluster == critical_cluster_id)


pipeline = Pipeline([('scaler', StandardScaler()), ('classifier', DecisionTreeClassifier(max_depth=3))])
pipeline.fit(X, y)

joblib.dump(pipeline, 'criticality_model.pkl')