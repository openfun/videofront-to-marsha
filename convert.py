import csv
import datetime
import os
import shutil
import tarfile
import uuid

import click
from slugify import slugify
import xml.etree.ElementTree as ET

"""
Uncompressed .tar.gz course is a flat representation of nested course structure, therefore each
element type (chapter, sequential, vertical) is stored in a folder of its type name on the
filesystem, and can be identified by its `url_name`. Ex. sequential/12ef45.xml, this file contains
url_names of its children elements which will be stored in their element type name folder.
"""


# Cloud front HD format url
CLOUDFRONT_URL = "https://d381hmu4snvm3e.cloudfront.net/videos/{videofront_id}/HD.mp4"
SHORT_CLOUDFRONT_URL = "videos/{videofront_id}/HD.mp4"

MARSHA_LAUNCH_URL = "https://marsha.education/lti/videos/{uuid}"

# lti_consumer default configuration
MARSHA_LTI_CONFIGURATION = {
    "xblock-family": "xblock.v1",
    "inline_height": "",
    "lti_id": "marsha_production_video",
    "launch_target": "iframe",
}


class ConvertCourse:
    def __init__(self, path, course_key, convert_video, vertical, consumer_site, create_archive, already_imported):
        """
        Initialize converter with command line parameters
        """
        if path.endswith("tar.gz"):
            self.extract_targz(path)
            path = "course"
            self.path = path
        self.base_path = os.getcwd()
        self.convert_video = convert_video
        self.consumer_site = consumer_site
        self.csv_file = None
        self.csv_filename = ""
        self.course_key = course_key
        self.create_archive = create_archive
        self.display_name = ""
        self.verticals_to_process = []
        self.already_imported = {}

        if already_imported:
            self.already_imported = self.read_already_imported_database(
                already_imported)
            print(f"Using {already_imported} containing {len(self.already_imported)} uuid")

        if vertical:
            self.verticals_to_process.append(vertical)

    def read_already_imported_database(self, filename):
        """
        Read CSV file wich contains legacy Marsha uuids which are already existing
        and can't be build from xblock_id.
        Returns a dict which keys are already processed xblock ids
        """
        already_imported = {}
        with open(filename) as csvfile:
            reader = csv.DictReader(csvfile, delimiter=";")

            for row in reader:
                xblock_id = row["xblock_id"]
                del row["xblock_id"]
                already_imported[xblock_id] = row
        return already_imported


    def extract_targz(self, file):
        """
        Extract course archive
        """
        print("Extracting {file}".format(file=file))
        targz = tarfile.open(file)
        targz.extractall()
        print("Extracted to {path}".format(path="course"))

    def create_new_targz(self, path="course"):
        """
        Create a nicely named tar.gz with processed course result.
        """
        filename = self.filename + ".tar.gz"
        with tarfile.open(os.path.join(self.base_path, "target", filename), "w:gz") as targz:
            targz.add(path)
            targz.close()
        print("Created new archive {filename}".format(filename=filename))

    def read_xmlfile(self, folder, url_name, getroot=True):
        """
        Read node xml file, returns ElementTree element
        """
        result = ET.parse(
            os.path.join(self.base_path, self.path, folder, url_name + ".xml")
        )
        if getroot:
            result = result.getroot()
        return result

    def write_xmlfile(self, element, folder, url_name):
        """
        Write node xml file
        """
        path = os.path.join(self.base_path, self.path, folder, url_name + ".xml")
        result = ET.ElementTree(element).write(path)
        return result

    def write_csv_file(self, xblock_url_name, videofront_id, marsha_uuid):
        """
        Write a line in CSV file
        """
        print("csv file: ", self.csv_file)
        if not self.csv_file:
            # Initialize CSV writer if not yet done
            file = open(os.path.join(self.base_path, "files", slugify(self.filename) + ".csv"), "w")
            self.csv_filename = file.name
            self.csv_file = csv.writer(
                file, delimiter=";", quotechar='"', quoting=csv.QUOTE_MINIMAL
            )
            # columns expected by Marsha import script
            self.csv_file.writerow(["consumer_site", "course_key", "xblock_id", "videofront_key", "uuid"])
        # build Cloudfront url from Videofront ID
        url = SHORT_CLOUDFRONT_URL.format(videofront_id=videofront_id.strip())
        # write one line
        self.csv_file.writerow([self.consumer_site, self.course_key, xblock_url_name, url, marsha_uuid])

    def get_uuid(self, xblock_id, videofront_id):
        """
        Returns a unique uuid for a given videofront ID, this ensure that different
        sessions of the same course do not upoad the same video again to Amazon
        """
        return uuid.uuid5(uuid.NAMESPACE_DNS, videofront_id)

    def get_or_create_uuid(self, xblock_id, videofront_id):
        """
        Returns a unique Marsha uuid for a given videofront_id.
        """
        if xblock_id in self.already_imported:
            marsha_uuid = self.already_imported[xblock_id]["uuid"]
            print(f"** Found a previously imported video {videofront_id} with uuid {marsha_uuid}")
            return marsha_uuid
        else:
            return uuid.uuid5(uuid.NAMESPACE_DNS, videofront_id)

    def process_verticals(self):
        """
        Rewrite vertical xml files containing xblocks we target.
        """
        for url_name in self.verticals_to_process:
            print("# ", url_name)
            vertical = self.read_xmlfile("vertical", url_name, getroot=True)

            print("Processing vertical {vertical}".format(vertical=url_name))
            for idx, xblock in enumerate(vertical):
                print("## ", idx, xblock, self.convert_video)
                if (
                    xblock.tag == "libcast_xblock" or xblock.tag == "video"
                ) and self.convert_video:
                    print(True)
                    if "video_id" not in xblock.attrib:
                        # if video_id is not present, conversion is impossible.
                        continue
                    if "group_access" in xblock.attrib:
                        # This is youtube player containing an url to a video
                        continue
                    marsha_uuid = ""
                    if self.convert_video == "youtube":
                        # replace libcast node by a new "video" one, that will point to a newly created video xml file
                        replace = ET.Element(
                            "video"
                        )  # create video node that will link to real video xml file
                        new_uuid = uuid.uuid4().hex
                        replace.attrib["url_name"] = new_uuid
                        del vertical[idx]  # delete libcast node
                        vertical.insert(idx, replace)  # insert video node

                        video_hd_url = CLOUDFRONT_URL.format(
                            videofront_id=xblock.attrib["video_id"]
                        )
                        os.makedirs(
                            os.path.join(self.base_path, self.path, "video"),
                            exist_ok=True,
                        )
                        video = ET.Element("video")  # create video file
                        video.attrib = {
                            "url_name": new_uuid,
                            "display_name": xblock.attrib["display_name"],
                            "download_video": xblock.attrib.get(
                                "allow_download", "true"
                            ),
                            "html5_sources": """["{video_hd_url}"]""".format(
                                video_hd_url=video_hd_url
                            ),
                            "sub": "",
                            "youtube_id_1_0": "",
                        }
                        source = ET.SubElement(video, "source")
                        source.attrib["src"] = video_hd_url
                        # save new video node
                        output_video = os.path.join(
                            self.base_path, self.path, "video", new_uuid + ".xml"
                        )
                        ET.ElementTree(video).write(output_video)
                        # replace original vertical xml file
                        output_vertical = os.path.join(
                            self.base_path, self.path, "vertical", url_name + ".xml"
                        )
                        ET.ElementTree(vertical).write(
                            output_vertical
                        )  # save video node in video folder
                        print(
                            "Replaced libcast_xblock {libcast_id} by youtube {youtube_id}".format(
                                libcast_id=xblock.attrib["url_name"],
                                youtube_id=video.attrib["url_name"],
                            )
                        )
                    elif self.convert_video == "marsha":
                        # LTI consumers don't have dedicated folder, they are inner children of their vertical
                        reuse_uuid = xblock.attrib[
                            "url_name"
                        ]  # retrieve xblock url_name
                        videofront_id = xblock.attrib[
                            "video_id"
                        ]  # retrieve videofront video id
                        del vertical[idx]
                        lti_consumer = ET.Element("lti_consumer")
                        lti_consumer.attrib = {**MARSHA_LTI_CONFIGURATION}
                        # generate marsha uuid from videofront ID
                        marsha_uuid = self.get_or_create_uuid(
                            reuse_uuid, xblock.attrib["video_id"])
                        lti_consumer.attrib["launch_url"] = MARSHA_LAUNCH_URL.format(uuid=marsha_uuid)
                        lti_consumer.attrib["display_name"] = xblock.attrib.get("display_name", "")
                        lti_consumer.attrib["url_name"] = reuse_uuid
                        vertical.insert(idx, lti_consumer)  # insert video node
                        self.write_xmlfile(vertical, "vertical", url_name)
                        print(
                            "Replaced libcast_xblock {url_name} by lti_consumer keeping same id".format(
                                url_name=reuse_uuid
                            )
                        )

                    self.write_csv_file(reuse_uuid, videofront_id, marsha_uuid)
        print("filename ", self.csv_filename)
        if self.csv_filename:
            print(
                "Video ids exported as CSV to {filename}".format(
                    filename=self.csv_filename
                )
            )
        else:
            print("Failed to export video ids as CSV")

    def process_course(self):
        """
        Read course structure and initialize converter,
        then iterate on chapters, sequences and verticals to find aimed nodes.
        """
        org, number, session = self.course_key.split(":")[1].split("+")
        root = self.read_xmlfile("", "course")
        assert org == root.attrib["org"]
        assert number == root.attrib["course"]

        # This node (chapters) contains "Advanced settings", course chapters and wiki url key
        chapters = self.read_xmlfile("course", root.attrib["url_name"])
        self.display_name = chapters.attrib["display_name"]
        print("Course name: {display_name}".format(display_name=self.display_name))

        # create file name used to save archive and csv
        self.filename = slugify(self.display_name)
        if self.convert_video:
            self.filename += "-{video}-".format(video=self.convert_video)
        self.filename += datetime.datetime.now().strftime("%Y-%m-%d")

        for chapter_url in chapters:
            if "url_name" in chapter_url.attrib:  # wiki is a chapter with no url
                chapter = self.read_xmlfile("chapter", chapter_url.attrib["url_name"])
                print(
                    "{p}Chapter name: {display_name}".format(
                        display_name=chapter.attrib["display_name"], p=" " * 4
                    )
                )
                for sequential_url in chapter:
                    sequential = self.read_xmlfile(
                        "sequential", sequential_url.attrib["url_name"]
                    )
                    print(
                        "{p}Sequential name: {display_name}".format(
                            display_name=sequential.attrib["display_name"], p=" " * 8
                        )
                    )

                    for vertical_url in sequential:
                        vertical = self.read_xmlfile(
                            "vertical", vertical_url.attrib["url_name"]
                        )
                        print(
                            "{p}Vertical name: {display_name}".format(
                                display_name=vertical.attrib["display_name"], p=" " * 12
                            )
                        )

                        for xblock in vertical:
                            if xblock.tag == "libcast_xblock":
                                self.verticals_to_process.append(
                                    vertical_url.attrib["url_name"]
                                )
                            if xblock.tag == "video":
                                # Strangely we also have libcast xblocks called "video"
                                print("Suspect video xblock")
                                self.verticals_to_process.append(
                                    vertical_url.attrib["url_name"]
                                )
        self.process_verticals()
        if self.create_archive:
            self.create_new_targz()


@click.command()
@click.argument("course_key")
@click.option(
    "--convert-video",
    type=click.Choice(choices=["youtube", "marsha"]),
    default="marsha",
    help="Convert FUN Videofront video xblock to youtube xblock or Marsha lti-consumer xblock",
)
@click.option(
    "--consumer-site",
    type=click.STRING,
    default="fun-mooc.fr",
    help="Value for consumer_site column when exporting to CSV",
)
@click.option(
    "--create-archive",
    is_flag=True,
    default=True,
    help="Create new archive with process result, ready to be imported in studio",
)
@click.option(
    "--already-imported", "-i",
    type=click.Path(
        exists=True, file_okay=True, dir_okay=False, writable=False, readable=True
    ),
    default=None,
    help="Provide a CSV file of already imported videos (when uuid calculation was random)",
)

@click.option(
    "--vertical",
    type=click.STRING,
    required=False,
    help="Target a specific vertical xblock",
)
def cli(course_key, convert_video, vertical, consumer_site, create_archive, already_imported):
    for path in os.listdir("source"):
        if path.endswith("tar.gz"):
            # Make sure the "course" directory is empty before extracting the course
            try:
                shutil.rmtree("course")
            except FileNotFoundError:
                pass
            os.mkdir('course')
            
            # Convert the course to Marsha
            convert = ConvertCourse(
                f"source/{path:s}", course_key, convert_video, vertical, consumer_site, create_archive, already_imported)
            convert.process_course()


if __name__ == "__main__":
    cli()
