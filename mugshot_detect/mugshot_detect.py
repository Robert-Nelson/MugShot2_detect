#!/usr/bin/env python3

# Copyright (c) 2020 Robert Nelson, All rights reserved.

import os.path
import sys
import time
from glob import glob
from deepface.detectors import FaceDetector
import numpy
import cv2
import mariadb as mysql
import argparse
import datetime
import json


def db_open(user, password, host, database):
    try:
        db_conn = mysql.connect(user=user, password=password, host=host, database=database)
    except mysql.Error as error:
        print("Error while connecting to mysql", error)
        db_conn = None
    return db_conn


def db_close(db_conn):
    db_conn.close()


def db_get_files_by_image(db_conn, start_image, end_image):
    db_cur = db_conn.cursor()
    rows = []
    try:
        db_cur.execute("SELECT path FROM piwigo_images WHERE id >= %s AND id <= %s", (start_image, end_image))
        rows = db_cur.fetchall()
    except mysql.Error as error:
        print("Error while getting list of files by image id", error)
    db_cur.close()
    result = []
    for row in rows:
        result.append(row[0])
    return result


def db_get_files_by_date(db_conn, start_image, end_image):
    db_cur = db_conn.cursor()
    rows = []
    try:
        db_cur.execute("SELECT path FROM piwigo_images WHERE date_available >= %s AND date_available <= %s",
                       (start_image, end_image))
        rows = db_cur.fetchall()
    except mysql.Error as error:
        print("Error while getting list of files by date", error)
    db_cur.close()
    result = []
    for row in rows:
        result.append(row[0])
    return result


def db_get_unidentified_tag_ids(db_conn, count):
    db_cur = db_conn.cursor()
    unknown_ids = []
    try:
        db_cur.execute("SELECT id FROM piwigo_tags WHERE name LIKE 'Unidentified Person%' ORDER BY id")
        rows = db_cur.fetchall()
        if len(rows) > 0:
            for row in rows:
                unknown_ids.append(int(row[0]))
    except mysql.Error as error:
        print("Error while getting the Unidentified Person tag list", error)

    if len(unknown_ids) >= count:
        db_cur.close()

        return unknown_ids

    dummy_tags = []
    count = int((count + 4) / 5) * 5

    name = "Unidentified Person #"
    url = "unidentified_person_#"
    for index in range(len(unknown_ids)+1, count+1):
        dummy_tags.append((name + str(index), url + str(index)),)

    try:
        sql_insert = (
            "INSERT INTO piwigo_tags (name, url_name, lastmodified)"
            "VALUES (%s, %s, NOW())"
        )
        db_cur.executemany(sql_insert, dummy_tags)
    except mysql.Error as error:
        print("Error while inserting Unidentified Person tags", error)

    db_cur.close()

    return db_get_unidentified_tag_ids(db_conn, count)


def db_get_image_id(db_conn, filename):
    db_cur = db_conn.cursor()
    image_id = 0
    try:
        db_cur.execute("SELECT id FROM piwigo_images WHERE path = %s OR file = %s",
                       (filename, os.path.basename(filename)))
        rows = db_cur.fetchall()
        assert len(rows) <= 1
        if len(rows) > 0:
            image_id = int(rows[0][0])
    except mysql.Error as error:
        print("Error while getting the image id for a file name", error)
    db_cur.close()
    return image_id


def db_get_url_name(db_conn, tag_id):
    db_cur = db_conn.cursor()
    url_name = ''
    try:
        db_cur.execute("SELECT url_name FROM piwigo_tags WHERE id = %s", (str(tag_id),))
        rows = db_cur.fetchall()
        assert len(rows) <= 1
        if len(rows) > 0:
            url_name = rows[0][0]
    except mysql.Error as error:
        print("Error while getting the url name for a specified tag", error)
    db_cur.close()
    return url_name


def db_fetchfaces(db_conn, image_id):
    db_cur = db_conn.cursor(named_tuple=True)
    rows = None
    try:
        sql_select = ("SELECT * FROM face_tag_positions as ftp "
                      "WHERE image_id = %s order by top, lft")
        db_cur.execute(sql_select, (image_id,))
        rows = db_cur.fetchall()
    except mysql.Error as error:
        print("Error while getting the faces for a specified image id", error)
    db_cur.close()
    return rows


def db_setfacepos(db_conn, new, updated):
    db_cur = db_conn.cursor()
    try:
        if len(new) > 0:
            sql_insert = (
                "INSERT INTO face_tag_positions "
                "(image_id, tag_id, top, lft, width, height, image_width, image_height) "
                "VALUES (%(image_id)s, %(tag_id)s, %(top)s, %(lft)s, %(width)s, %(height)s, %(image_width)s, "
                "%(image_height)s)")
            db_cur.executemany(sql_insert, new)
            sql_insert = (
                "INSERT INTO piwigo_image_tag "
                "(image_id, tag_id) VALUES (%(image_id)s, %(tag_id)s)")
            db_cur.executemany(sql_insert, new)
            db_conn.commit()
        if len(updated) > 0:
            sql_update = (
                "UPDATE face_tag_positions "
                "SET image_id=%(image_id)s, tag_id=%(tag_id)s, top=%(top)s, lft=%(lft)s, width=%(width)s, "
                "height=%(height)s, image_width=%(image_width)s, image_height=%(image_height)s "
                "WHERE image_id = %(image_id)s AND tag_id = %(tag_id)s")
            db_cur.executemany(sql_update, updated)
            db_conn.commit()
    except mysql.Error as error:
        print("Error adding and updating the faces for specified image id", error)
    finally:
        db_cur.close()


# (left, top, left+width, top+height)
def rect_area(rect1, rect2):
    dx = min(rect1[2], rect2[2]) - max(rect1[0], rect2[0])
    dy = min(rect1[3], rect2[3]) - max(rect1[1], rect2[1])
    if (dx >= 0) and (dy >= 0):
        return dx * dy
    else:
        return 0


def main():
    prog_desc = ""
    help_epilog = ""
    remote_exec_description = ""

    parser = argparse.ArgumentParser(description=prog_desc, epilog=help_epilog, )
    parser.add_argument("--config", "-c", type=str, nargs=1, required=True, metavar="CONFIG.JSON")
    remote_exec_group = parser.add_argument_group(title="Optional Remote Execution",
                                                  description=remote_exec_description)
    remote_exec_group.add_argument("--training", "-t", type=str, nargs=1)
    remote_exec_group.add_argument("--uploads", "-u", type=str, nargs=1)

    input_list_group = parser.add_mutually_exclusive_group(required=True)
    input_list_group.add_argument("--files", "-f", type=str, nargs='+')
    input_list_group.add_argument("--images", "-i", type=int, nargs=2, metavar=('START_IMAGE_#', 'END_IMAGE_#'))
    input_list_group.add_argument("--dates", "-d", type=str, nargs=2, metavar=('START_DATE', 'END_DATE'))

    args = parser.parse_args()

    with open(args.config[0], "r") as fp:
        config = json.load(fp)

    if args.training[0] is not None:
        training_dir = args.training[0]
    else:
        training_dir = './plugins/MugShot/training'

    if args.uploads[0] is not None:
        uploads_dir = args.uploads[0]
    else:
        uploads_dir = './upload/'

    # set opencv, ssd, dlib, mtcnn or retinaface
    detector_name = "retinaface"
    # detector_name = "mtcnn"
    detector = FaceDetector.build_model(detector_name)

    conn = db_open(user=config["user"], password=config["password"], host=config["host"], database=config["database"])

    if args.images is not None:
        print("[INFO] Processing images from ", args.images[0], "to ", args.images[1])
        filelist = db_get_files_by_image(conn, args.images[0], args.images[1])
    elif args.dates is not None:
        print("[INFO] Processing dates from", args.dates[0], "to", args.dates[1])
        filelist = db_get_files_by_date(conn, args.dates[0], args.dates[1])
    elif args.files is not None:
        filelist = args.files
    else:
        filelist = []

    print("[INFO]", len(filelist), "files")

    orig_dir = os.getcwd()
    os.chdir(uploads_dir)

    for file_pattern in filelist:
        file_pattern = file_pattern.replace('./upload/', '')
        for img_basename in glob(file_pattern):
            print("[INFO] Processing ", img_basename)
            image_id = db_get_image_id(conn, './upload/' + img_basename)
            if image_id > 0:
                img = cv2.imread(img_basename)

                start = time.time()
                detected_faces = FaceDetector.detect_faces(detector, detector_name, img)
                end = time.time()

                print("[INFO] face detection took {:.4f} seconds".format(end - start))
                print("[INFO] there are ", len(detected_faces), " faces")

                faces = db_fetchfaces(conn, image_id)

                unknown_ids = db_get_unidentified_tag_ids(conn, len(detected_faces))

                faces_list = []
                for detected in detected_faces:
                    detected_bbox = detected[1]
                    db_facepos = {
                        'image_id': image_id, 'tag_id': None, 'top': int(detected_bbox[1]),
                        'lft': int(detected_bbox[0]), 'width': int(detected_bbox[2]), 'height': int(detected_bbox[3]),
                        'image_width': int(img.shape[1]), 'image_height': int(img.shape[0])
                    }

                    if len(faces) > 0:
                        r1 = (detected_bbox[0], detected_bbox[1],
                              int(detected_bbox[0] + detected_bbox[2]), int(detected_bbox[1] + detected_bbox[3]))

                        for previous in faces:
                            scale_factor = float(img.shape[1]) / float(previous.image_width)

                            r2 = (previous.lft * scale_factor, previous.top * scale_factor,
                                  (previous.lft+previous.width) * scale_factor,
                                  (previous.top+previous.height) * scale_factor)

                            area = rect_area(r1, r2)
                            percentage = float(area) / (float(detected_bbox[2]) * float(detected_bbox[3])) * 100.0

                            if percentage > 75:
                                db_facepos['tag_id'] = int(previous.tag_id)
                                try:
                                    unknown_ids.remove(int(previous.tag_id))
                                except ValueError:
                                    pass
                                break

                    faces_list.append((db_facepos, detected[0]))

                new_faces = []
                updated_faces = []

                for db_facepos, faceimg in faces_list:
                    if db_facepos['tag_id'] is None:
                        db_facepos['tag_id'] = unknown_ids.pop(0)
                        new_faces.append(db_facepos)
                    else:
                        updated_faces.append(db_facepos)

                    url_name = db_get_url_name(conn, db_facepos['tag_id'])
                    file_name = os.path.join(training_dir, url_name, str(image_id) + str(db_facepos['tag_id']) + '.jpg')
                    directory = os.path.dirname(file_name)
                    if not os.path.exists(directory):
                        os.makedirs(directory)
                    cv2.imwrite(file_name, faceimg)

                db_setfacepos(conn, new_faces, updated_faces)
            else:
                print("WARNING: ", img_filename, "hasn't been added or has been removed - skipping")

    db_close(conn)


if __name__ == '__main__':
    sys.exit(main())
