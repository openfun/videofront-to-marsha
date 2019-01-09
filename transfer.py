import csv
from datetime import datetime
from html import unescape
import json
import os
import re
from urllib.parse import unquote
import urllib3

import boto3
import click
from oauthlib import oauth1
import requests

# Ignore insecure requests warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Instantiate a boto3 client to interact with AWS S3:
marsha_s3 = boto3.client(
    "s3",
    region_name=os.environ.get("MARSHA_AWS_REGION", "eu-west-1"),
    aws_access_key_id=os.environ["MARSHA_AWS_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["MARSHA_AWS_SECRET_ACCESS_KEY"],
)


def copy_object(videofront_key, marsha_bucket, marsha_key):
    """Copy an object from VideoFront to Marsha without downloading it.
    
    Note: this requires that the Marsha AWS account have access to VideoFront's bucket.
    If it is in another account, you need to add the following bucket policy to your
    VideoFront S3 bucket:

        {
            "Sid": "1",
            "Effect": "Allow",
            "Principal": {
                "AWS": "arn:aws:iam::{marsha_account_id}:user/{marsha_user_name}"
            },
            "Action": "s3:*",
            "Resource": [
                "arn:aws:s3:::{videofront_bucket_name}/*",
                "arn:aws:s3:::{videofront_bucket_name}"
            ]
        }

    """
    copy_source = {
        "Bucket": os.environ["VIDEOFRONT_BUCKET_NAME"],
        "Key": videofront_key,
    }
    marsha_s3.copy(copy_source, marsha_bucket, marsha_key)


def get_or_create_video(videofront_key, course_key, xblock_id, uuid):
    """
    This function handles all the steps necessary to transfer a video from VideoFront to Marsha:
    - Handcraft an LTI launch request to Marsha that will get or create a video object (and its
      related playlist) with the provided `xblock_id` and `course_key`,
    - Send the LTI launch request to Marsha and get in return a JWT Token and information about
      the state of this video in Marsha,
    - If the video has not yet been successfully uploaded, copy the file from VideoFront's S3
      bucket to Marsha's S3 bucket using the provided "videofront_key`.
    - Inspect the VideoFront S3 bucket to see what subtitle files existed,
    - Using Marsha's Rest API (now that we have a JWT Token for the video), get or create timed
      text track objects in Marsha for each subtitle that existed in VideoFront,
    - For each timed text track that had not yet been successfully uploaded to Marsha, copy the
      file from VideoFront's S3 bucket to Marsha's S3 bucket.

    FIXME: this code could be greatly simplified by adding in Marsha the possibility to
    authenticate via a token and directly interact with the API instead of the LTI view...
    """
    lti_parameters = {
        "resource_link_id": "{:s}-{:s}".format(
            os.environ["MARSHA_CONSUMER_SITE_DOMAIN"], xblock_id
        ),
        "context_id": course_key,
        "user_id": "vf2m",
        "lis_person_contact_email_primary": "fun.dev@fun-mooc.fr",
        "roles": "Instructor",
    }
    lti_launch_url = "{:s}/lti/videos/{:s}".format(os.environ["MARSHA_BASE_URL"], uuid)

    client = oauth1.Client(
        client_key=os.environ["MARSHA_OAUTH_CONSUMER_KEY"],
        client_secret=os.environ["MARSHA_SHARED_SECRET"],
    )
    # Compute Authorization header which looks like:
    # Authorization: OAuth oauth_nonce="80966668944732164491378916897",
    # oauth_timestamp="1378916897", oauth_version="1.0", oauth_signature_method="HMAC-SHA1",
    # oauth_consumer_key="", oauth_signature="frVp4JuvT1mVXlxktiAUjQ7%2F1cw%3D"
    _uri, headers, _body = client.sign(
        lti_launch_url,
        http_method="POST",
        body=lti_parameters,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    # Parse headers to include the parameters in the LTI payload
    oauth_dict = {
        k: v
        for k, v in [
            param.strip().replace('"', "").split("=")
            for param in headers["Authorization"].split(",")
        ]
    }
    signature = oauth_dict["oauth_signature"]
    oauth_dict["oauth_signature"] = unquote(signature)
    oauth_dict["oauth_nonce"] = oauth_dict.pop("OAuth oauth_nonce")

    lti_parameters.update(oauth_dict)
    response = requests.post(
        lti_launch_url,
        data=lti_parameters,
        headers={"referer": os.environ["MARSHA_CONSUMER_SITE_REFERER"]},
        verify=False,
    )

    # Extract the video data from response
    data_string = re.search(
        '<div class="marsha-frontend-data" id="video" data-video="(.*)">', response.text
    ).group(1)
    data = json.loads(unescape(data_string))

    # Extract the JWT Token from response
    jwt_token = re.search(
        '<div class="marsha-frontend-data" data-jwt="(.*)" data-state="instructor"',
        response.text,
    ).group(1)

    # Get an upload policy and copy the video only if it has not yet been successfully uploaded
    if data["upload_state"] == "pending":
        upload_policy = requests.post(
            "{:s}/api/videos/{!s}/initiate-upload/".format(
                os.environ["MARSHA_BASE_URL"], data["id"]
            ),
            headers={"authorization": "Bearer {!s}".format(jwt_token)},
            verify=False,
        ).json()
        copy_object(videofront_key, upload_policy["bucket"], upload_policy["key"])

    # Get the list of existing subtitle tracks for this video in Marsha
    ttt_list = requests.get(
        "{:s}/api/timedtexttracks/".format(os.environ["MARSHA_BASE_URL"]),
        headers={"authorization": "Bearer {!s}".format(jwt_token)},
        verify=False,
    ).json()
    ttt_dict = {o["language"]: o for o in ttt_list}

    # Retrieve the subtitle files existing for this video in VideoFront
    for videofront_obj in marsha_s3.list_objects(
        Bucket=os.environ["VIDEOFRONT_BUCKET_NAME"],
        Delimiter="/",
        Prefix="/".join(videofront_key.split("/")[:2]) + "/subs/",
    ).get("Contents", []):
        ttt_videofront_key = videofront_obj["Key"]

        # Create the timed text track in Marsha if it does not exist
        language = ttt_videofront_key.rsplit(".", 2)[-2]
        if language not in ttt_dict:
            ttt_data = {"language": language, "mode": "st"}
            ttt_dict[language] = requests.post(
                "{:s}/api/timedtexttracks/".format(os.environ["MARSHA_BASE_URL"]),
                headers={"authorization": "Bearer {!s}".format(jwt_token)},
                data=ttt_data,
                verify=False,
            ).json()

        # Get an upload policy and copy the track only if it has not yet been
        # successfully uploaded
        if ttt_dict[language]["upload_state"] == "pending":
            upload_policy = requests.post(
                "{:s}/api/timedtexttracks/{!s}/initiate-upload/".format(
                    os.environ["MARSHA_BASE_URL"], ttt_dict[language]["id"]
                ),
                headers={"authorization": "Bearer {!s}".format(jwt_token)},
                verify=False,
            ).json()
            copy_object(
                ttt_videofront_key, upload_policy["bucket"], upload_policy["key"]
            )


@click.command()
@click.argument("filename")
def cli(filename):
    """The click command.

    Opens the csv file passed in argument and lets the `get_or_create` function handle the
    transfer from VideoFront to Marsha for each row in the file.

    The file must be a csv, with ";" delimiter and three columns:
        
        course_key;xblock_id;videofront_key
        course/CNAM/01007;2222224390634859b246ff75d2c7ba24;videos/00RcKZhbiBUt/HD.mp4
        .../...

    where:
    - course key: the course identifier that will be associated to the playlist in Marsha. It
        is common to all the videos of a same course,
    - xblock_id: the unique identifier of the LTI Xblock in which the Marsha video is declared
        in Open edX. It is used as `resource_id` for the video in Marsha.
    - videofront_key: the key, in VideoFront's AWS S3 bucket, under which we find the file of
        the video. We will use this key to copy the file directly from VideoFront's S3 bucket to
        Marsha's S3 bucket.
    """
    with open("files/{:s}".format(filename), "r") as csvfile:
        for row in csv.DictReader(csvfile, delimiter=";"):
            print(" | ".join(row.values()))
            get_or_create_video(**row)


if __name__ == "__main__":
    cli()
