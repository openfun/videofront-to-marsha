## VideoFront to Marsha

A small [click](https://click.palletsprojects.com) project to automate the
transfer of videos and subtitles from your VideoFront S3 bucket to Marsha.

## Getting started

### Prerequisites

The transfer script runs in Docker. Make sure you have a recent version of
Docker installed on your laptop:

```bash
$ docker -v
  Docker version 18.09.0, build 4d60db4
```

⚠️ You may need to run the following commands with `sudo` but this can be
avoided by assigning your user to the `docker` group.

### Manifest file

You need to generate a manifest of the videos you want to transfer. It should
be a csv file of the form:

```
course_key;xblock_id;videofront_key;uuid
course/edufree/01007;1234564390634859b246ff75d2c7ba24;videos/00RcKZhbiBUt/HD.mp4;1e93eac2-1acb-45b4-8dfc-700c1af6c031
.../...
```

where:
- course key: the course identifier that will be associated to the playlist in Marsha. It
    is common to all the videos of a same course,
- xblock_id: the unique identifier of the LTI Xblock in which the Marsha video is declared
    in Open edX.
- videofront_key: the key, in VideoFront's AWS S3 bucket, under which we find the file of
    the video. We will use this key to copy the file directly from VideoFront's S3 bucket to
    Marsha's S3 bucket.
- uuid: the unique ID with which the video will be created in Marsha. It is the UUID you
    used in the randomly generated LTI launch url of your XBlock of the form:
    https://marsha.education/lti/videos/1e93eac2-1acb-45b4-8dfc-700c1af6c031

Place your manifest in the `files` directory where Docker can find it. Don't worry, it will
be git-ignored.

### Transfer script

Build the Docker image of the project and initialize an environment file:

    $ make build

You should now see a new file `env.d/local`. Replace each setting by your credentials as
suggested in the file.

Run the script against your manifest file:

    $ bin/vf2m transfer.py my_manifest.csv

## License

This work is released under the MIT License (see [LICENSE](./LICENSE)).
