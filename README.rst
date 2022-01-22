==============
mugshot_detect
==============

**Summary**

This application enhances the MugShot plugin for PiWiGo.  It can be run periodically to scan a group of photos to
detect the faces located in the photo. For each face detected the bounding box is determined and the coordinates are
stored in the database. This automates the process previously used where the user selects the face by dragging the
mouse from one corner to its diagonally opposite corner.

Each detected face is tagged with a place holder name "Unidentified Person #1", "Unidentified Person #2", etc. At any
time the faces can be reassigned to the proper person with the correct name by the user switching to tagging mode,
then double clicking on the face and entering the actual name.

**Process**

The photos to be scanned can be specified by date, by image number or by file name. Access to the database server,
the upload directory containing the photos and the training directory where the cropped face are stored.

The simplest method is to run this application directly on the web server with the PiWiGo top level directory as the
current directory. But that is not always possible due to the load on the web server or needed software not available.

This software can be run on a separate machine. This enables hardware acceleration using NVIDIA CUDA Graphics Cards.
The only requirement is the availability of SSH to access the upload directory tree in the PiWiGo root and the
training tree at the root of the MugShot plugin. The trees can by made available as remote filesystems using a tool
like SSHFS ( https://github.com/libfuse/sshfs) on Linux and SSHFS-Win (https://github.com/billziss-gh/sshfs-win) and SSHFS-Win
Manager (https://github.com/evsar3/sshfs-win-manager) on Windows.
