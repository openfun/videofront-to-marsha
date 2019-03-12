import boto3
import os
import re

# Instantiate a boto3 client to interact with AWS S3:
marsha_s3 = boto3.client(
    "s3",
    region_name=os.environ.get("MARSHA_AWS_REGION", "eu-west-1"),
    aws_access_key_id=os.environ["MARSHA_AWS_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["MARSHA_AWS_SECRET_ACCESS_KEY"],
)

paginator = marsha_s3.get_paginator('list_objects')
response_itrator = paginator.paginate(
  Bucket=os.environ["MARSHA_BUCKET_NAME"],
)

regex = re.compile(r"^.*\/mp4\/.*_(1080|720|480|240|144)\.mp4$")

for response in response_itrator:
  for video in response.get("Contents"):
    if regex.match(video.get("Key")):
      print("updating key: {}".format(video.get("Key")))
      marsha_s3.copy_object(
        Bucket=os.environ["MARSHA_BUCKET_NAME"],
        Key=video.get("Key"),
        ContentType="binary/octet-stream",
        MetadataDirective="REPLACE",
        CopySource={"Bucket": os.environ["MARSHA_BUCKET_NAME"], "Key": video.get("Key")}
      )
