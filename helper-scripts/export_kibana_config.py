#!/usr/bin/python3
"""
Helper script to export Kibana and Elastic Search objects
"""
import json
import re
import argparse
import sys
import os
import requests
import ndjson
from pprint import pprint

# Quick hack to disable invalid cert warning
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

SCHEME = "https"
KIBANA_URL = SCHEME + "://localhost:5601"
KIBANA_OBJECTS_EXPORT_URL = KIBANA_URL + "/api/saved_objects/_export"
REDELK_OBJ_FILTER = "RedELK"
INDEX_PATTERNS_FILTER = (
    "rtops|redirtraffic|implantsdb|bluecheck|credentials|email|redelk|.siem-signals"
)
EXPORT_FILES_PREFIX_KIBANA = "redelk_kibana_"
ES_URL = SCHEME + "://localhost:9200"
ES_TEMPLATES_LIST = [
    "rtops",
    "redirtraffic",
    "implantsdb",
    "bluecheck",
    "credentials",
    "email",
    "redelk",
]
EXPORT_FILES_PREFIX_ES = "redelk_elasticsearch_"
DIFF_PATH = "diff/"  # path is relative to exportpath
ENV_FILE = "../elkserver/.env"


class KibanaExporter:
    """
    Kibana exporter
    Use it to export data related to RedELK from Kibana and ES
    """

    def __init__(self, cmd_line_args) -> None:
        self.args = cmd_line_args
        self.base_path = os.path.dirname(os.path.abspath(__file__))

        if self.args.all:
            self.kibana_objects = [
                "index-pattern",
                "search",
                "visualization",
                "dashboard",
                "map",
            ]
        else:
            self.kibana_objects = []
            if self.args.indexpattern:
                self.kibana_objects.append("index-pattern")
            if self.args.search:
                self.kibana_objects.append("search")
            if self.args.visualization:
                self.kibana_objects.append("visualization")
            if self.args.dashboard:
                self.kibana_objects.append("dashboard")
            if self.args.map:
                self.kibana_objects.append("map")
        try:
            with open(ENV_FILE, "r") as env_file:
                for line in env_file.readlines():
                    if "CREDS_redelk=" in line:
                        env_file_password = line.split("=")[1].strip()
        except:
            print("Error opening password file")

        self.kibana_user = (
            cmd_line_args.username if cmd_line_args.username else "redelk"
        )
        self.kibana_password = (
            cmd_line_args.password if cmd_line_args.password else env_file_password
        )
        self.export_path = (
            cmd_line_args.exportpath
            if cmd_line_args.exportpath
            else os.path.join(
                self.base_path,
                "../elkserver/docker/redelk-base/redelkinstalldata/templates",
            )
        )
        self.diff_exportpath = os.path.join(self.export_path, DIFF_PATH)
        if not os.path.exists(self.diff_exportpath):
            os.makedirs(self.diff_exportpath)

    def run_script(self):
        """
        Run the different export / process based on arguments passed to command line
        """
        for kibana_object in self.kibana_objects:
            if self.args.export:
                self.fetch_kibana_object(kibana_object)
            if self.args.process:
                self.process_kibana_object(kibana_object)

        if self.args.estemplate or self.args.all:
            if self.args.export:
                self.fetch_es_templates()

    def fetch_kibana_object(self, obj_type):
        """
        Get saved object from Kibana API
        """
        try:
            print("# Fetching kibana objects: %s" % obj_type)
            response = requests.post(
                KIBANA_OBJECTS_EXPORT_URL,
                json={"type": obj_type},
                verify=False,
                auth=(self.kibana_user, self.kibana_password),
                headers={"kbn-xsrf": "true"},
            )
            if response.status_code != 200:
                print(
                    "!!! Error fetching kibana object %s: HTTP status code %s"
                    % (obj_type, response.status_code)
                )
            else:
                raw_data = response.text.encode("utf-8")
                items = ndjson.loads(raw_data)
                if obj_type != "index-pattern":
                    to_export = []
                    for ip in items:
                        if "attributes" in ip.keys() and "title" in ip["attributes"]:
                            if re.match(
                                REDELK_OBJ_FILTER,
                                ip["attributes"]["title"],
                                re.IGNORECASE,
                            ):
                                ip.pop("updated_at", None)
                                ip["version"] = "1"
                                to_export.append(ip)
                    export_file = os.path.join(
                        self.export_path,
                        "%s%s.ndjson" % (EXPORT_FILES_PREFIX_KIBANA, obj_type),
                    )
                    print("\tExporting %s: %s" % (obj_type, export_file))
                    with open(export_file, "w") as f:
                        ndjson.dump(to_export, f)
                else:
                    for ip in items:
                        if "attributes" in ip.keys() and "title" in ip["attributes"]:
                            if re.match(
                                INDEX_PATTERNS_FILTER,
                                ip["attributes"]["title"],
                                re.IGNORECASE,
                            ):
                                # print('%s: %s' % (obj_type,ip['attributes']['title']))
                                index_pattern_name = (
                                    ip["attributes"]["title"][:-2]
                                    if ip["attributes"]["title"].endswith("-*")
                                    else ip["attributes"]["title"]
                                )
                                ip.pop("updated_at", None)
                                ip["version"] = "1"
                                export_file = os.path.join(
                                    self.export_path,
                                    "%s%s_%s.ndjson"
                                    % (
                                        EXPORT_FILES_PREFIX_KIBANA,
                                        obj_type,
                                        index_pattern_name,
                                    ),
                                )
                                print("\tExporting %s: %s" % (obj_type, export_file))
                                with open(export_file, "w") as f:
                                    ndjson.dump([ip], f)
        except Exception as e:
            print("!!! Error fetching kibana object %s: %s" % (obj_type, e))

    def fetch_es_templates(self):
        """
        Get ElasticSearch template from API
        """
        for template_name in ES_TEMPLATES_LIST:
            try:
                print("# Fetching ES template: %s" % template_name)
                response = requests.get(
                    "%s/_template/%s" % (ES_URL, template_name),
                    verify=False,
                    auth=(self.kibana_user, self.kibana_password),
                )
                raw_data = response.text.encode("utf-8")
                tmpl = json.loads(raw_data)
                export_file = os.path.join(
                    self.export_path,
                    "%stemplate_%s.json" % (EXPORT_FILES_PREFIX_ES, template_name),
                )
                print(
                    "\tExporting index template %s: %s" % (template_name, export_file)
                )
                with open(export_file, "w") as template_file:
                    json.dump(
                        tmpl[template_name], template_file, indent=4, sort_keys=True
                    )
            except Exception as e:
                print("!!! Error fetching ES template %s: %s" % (template_name, e))

    def process_kibana_object(self, obj_type, indexpattern=None):
        """
        Create json from ndjson kibana object to ease diff during commits
        """
        print("# Processing kibana object: %s" % obj_type)

        if obj_type != "index-pattern":
            src_file_name = "%s%s" % (EXPORT_FILES_PREFIX_KIBANA, obj_type)
        else:
            if indexpattern is None:
                for i in INDEX_PATTERNS_FILTER.split("|"):
                    self.process_kibana_object(obj_type, indexpattern=i)
                return
            else:
                src_file_name = "%s%s_%s" % (
                    EXPORT_FILES_PREFIX_KIBANA,
                    obj_type,
                    indexpattern,
                )

        src_file = os.path.join(self.export_path, "%s.ndjson" % src_file_name)
        diff_file = os.path.join(self.export_path, DIFF_PATH, "%s.json" % src_file_name)
        print("\tOpening %s: %s" % (obj_type, src_file))
        with open(src_file, "r") as src_ndjson_file:
            src_ndjson = ndjson.load(src_ndjson_file)

        for src_ndjson_line in src_ndjson:
            if obj_type == "index-pattern":
                src_ndjson_line["attributes"]["fields"] = sorted(
                    json.loads(src_ndjson_line["attributes"]["fields"]),
                    key=lambda x: x["name"],
                )
            elif obj_type == "search":
                src_ndjson_line["attributes"]["kibanaSavedObjectMeta"][
                    "searchSourceJSON"
                ] = json.loads(
                    src_ndjson_line["attributes"]["kibanaSavedObjectMeta"][
                        "searchSourceJSON"
                    ]
                )
            elif obj_type == "visualization":
                src_ndjson_line["attributes"]["kibanaSavedObjectMeta"][
                    "searchSourceJSON"
                ] = json.loads(
                    src_ndjson_line["attributes"]["kibanaSavedObjectMeta"][
                        "searchSourceJSON"
                    ]
                )
                src_ndjson_line["attributes"]["visState"] = json.loads(
                    src_ndjson_line["attributes"]["visState"]
                )
            elif obj_type == "dashboard":
                src_ndjson_line["attributes"]["kibanaSavedObjectMeta"][
                    "searchSourceJSON"
                ] = json.loads(
                    src_ndjson_line["attributes"]["kibanaSavedObjectMeta"][
                        "searchSourceJSON"
                    ]
                )
                src_ndjson_line["attributes"]["optionsJSON"] = json.loads(
                    src_ndjson_line["attributes"]["optionsJSON"]
                )
                src_ndjson_line["attributes"]["panelsJSON"] = json.loads(
                    src_ndjson_line["attributes"]["panelsJSON"]
                )

        print("\tWriting output to: %s" % diff_file)
        with open(diff_file, "w") as dst_json_file:
            json.dump(src_ndjson, dst_json_file, indent=4, sort_keys=True)


def check_args():
    """
    Checks arguments passed to the script
    """
    parser = argparse.ArgumentParser(description="")
    parser.add_argument(
        "--exportpath",
        metavar="<exportpath>",
        dest="exportpath",
        help="Path to export the objects",
    )
    parser.add_argument(
        "--indexpattern", action="store_true", help="Export Kibana index patterns"
    )
    parser.add_argument("--search", action="store_true", help="Export Kibana searches")
    parser.add_argument(
        "--visualization", action="store_true", help="Export Kibana visualizations"
    )
    parser.add_argument(
        "--dashboard", action="store_true", help="Export Kibana dashboards"
    )
    parser.add_argument("--map", action="store_true", help="Export Kibana maps")
    parser.add_argument(
        "--estemplate", action="store_true", help="Export Elasticsearch templates"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Export all Kibana objects (similar to --indexpattern --search --visualizations --dashboards --estemplate --maps)",
    )
    parser.add_argument(
        "--export",
        action="store_true",
        help="Export data   (either --export of --process required)",
    )
    parser.add_argument(
        "--process",
        action="store_true",
        help="Process locally saved NDJSON files for easy diff   (either --export of --process required)",
    )
    parser.add_argument(
        "--username",
        metavar="<username>",
        dest="username",
        help="Elastic username, if not provided default 'redelk' is used",
    )
    parser.add_argument(
        "--password",
        metavar="<password>",
        dest="password",
        help="Elastic password, if not provided config file ../elkserver/.env will be parsed",
    )

    script_args = parser.parse_args()

    if (
        not script_args.indexpattern
        and not script_args.search
        and not script_args.visualization
        and not script_args.dashboard
        and not script_args.all
        and not script_args.estemplate
        and not script_args.map
        and not (script_args.export or script_args.process)
    ):
        print("[X] Missing argument")
        sys.exit(-1)

    if not script_args.export and not script_args.process:
        print("[X] Either --export of --process argument required")
        sys.exit(-1)

    return script_args


if __name__ == "__main__":

    args = check_args()

    exporter = KibanaExporter(args)
    exporter.run_script()
