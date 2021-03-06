# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 3
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####

# <pep8 compliant>

# Input/Output routines for VTK Unstructured Grid XML (VTU) format.

# More information about VTK: https://vtk.org/
# More information about VTK file formats:
# https://lorensen.github.io/VTKExamples/site/VTKFileFormats/

# Note: VTK Unstructured Grid's don't seem to support patches
# (named boundaries) or zones.

import bpy
from bpy_extras.io_utils import (
    ImportHelper,
    ExportHelper,
    orientation_helper,
    axis_conversion,
)
from . import ug
from . import ug_op
import logging
l = logging.getLogger(__name__)

# Global variables
print_interval = 10000 # Debug print progress interval
fulldebug = False # Set to True if you wanna see walls of logging debug


##################
##### IMPORT #####
##################

class UG_OT_ImportVtu(bpy.types.Operator, ImportHelper):
    '''Import VTK Unstructured Grid (.vtu) Files into Blender as UG Data'''
    bl_idname = "unstructured_grids.import_vtu"
    bl_label = "Import VTK Unstructured Grid (.vtu) (UG)"
    filename_ext = ".vtu"

    @classmethod
    def poll(cls, context):
        return context.mode in {'OBJECT','EDIT_MESH'}

    def execute(self, context):
        text = read_vtu_files(self)
        res = validate_vtu(text)
        if res:
             self.report({'ERROR'}, "Validation failed: " + res)
             return {'FINISHED'}
        n = vtu_to_ugdata(text)
        ug.update_ug_all_from_blender(self)
        self.report({'INFO'}, "Imported %d cells" % n)
        return {'FINISHED'}


def read_vtu_files(self):
    '''Read VTU file contents into string variable'''

    import os
    ug_props = bpy.context.scene.ug_props
    filepath = self.filepath

    if not (os.path.isfile(filepath)):
        self.report({'ERROR'}, "Could not find %r" \
                    % filepath)
        return None

    with open(filepath, 'r') as infile:
        text = infile.read()

    return text


def validate_vtu(text):
    '''Validate VTU data is suitable for parsing'''

    import re
    rec1 = re.compile(r'VTKFile\ type\=\"(.*?)\"', re.M)
    rec2 = re.compile(r'\ format\=\"(.*?)\"', re.M)

    if not text:
        return "Error: No file was selected"

    match = False
    for line in text.splitlines():
        regex1 = rec1.search(line)
        if regex1:
            match = True
            value = str(regex1.group(1))
            if value != "UnstructuredGrid":
                return "VTK file type is not 'UnstructuredGrid' but " + value
        regex2 = rec2.search(line)
        if regex2:
            value = str(regex2.group(1))
            if value != "ascii":
                return "VTK file format is not 'ascii' but " + value

    if not match:
        return "Error: File does not seem to be in VTU format"


def vtu_to_ugdata(text):
    '''Convert VTU data from text into UG data structures and Blender
    mesh
    '''

    import bmesh
    ug_props = bpy.context.scene.ug_props
    ug.hide_other_objects()
    ob = ug.initialize_ug_object()
    bm = bmesh.new()

    # Get lists of data from text
    l.debug("Reading points")
    points = get_data_array_block("Points", "float", text)
    l.debug("Reading connectivities")
    connectivities = get_data_array_block("connectivity", "int", text)
    l.debug("Reading offsets")
    offsets = get_data_array_block("offsets", "int", text)
    l.debug("Reading types")
    celltypes = get_data_array_block("types", "int", text)
    l.debug("Reading faces")
    cellfaces = get_data_array_block("faces", "int", text)
    l.debug("Reading faceoffsets")
    cellfaceoffsets = get_data_array_block("faceoffsets", "int", text)

    l.debug("VTU data contains %d coordinates" % len(points) \
            + ", %d connectivities" % len(connectivities) \
            + ", %d offsets" % len(offsets) \
            + ", %d celltypes" % len(celltypes) \
            + ", %d cellfaces" % len(cellfaces) \
            + " and %d cellfaceoffsets" % len(cellfaceoffsets))

    create_points(bm, points)
    vtu_datalists_to_ugdata(connectivities, offsets, celltypes, \
                            cellfaces, cellfaceoffsets)
    bm = create_boundary_faces(bm)
    # Add default boundary
    patch = ug.UGBoundary("default")
    bpy.ops.object.mode_set(mode='OBJECT')
    bm.to_mesh(ob.data)
    return len(celltypes)


def get_data_array_block(name, vartype, text):
    '''Return list of items (type vartype) in DataArray name from text'''

    import re
    rec1 = re.compile(r'\<DataArray\ .*Name\=\"(.*?)\"', re.M)
    rec2 = re.compile(r'\<\/DataArray\>', re.M)
    inside = False
    datablock = ""

    for line in text.splitlines():
        # Detect start of wanted section
        regex1 = rec1.search(line)
        if regex1:
            if str(regex1.group(1)) == name:
                inside = True
                continue
            else:
                inside = False

        # Detect end of wanted section
        regex2 = rec2.search(line)
        if regex2:
            inside = False

        # Add line if it is inside wanted section
        if inside:
            datablock += line

    return get_list_from_text(datablock, vartype)


def get_list_from_text(text, vartype):
    '''Creates list from argument text block by taking anything separated
    by spaces and then converting it to type vartype
    '''

    valuelist = []
    for value in text.split( ):
        value = value.strip()
        if value:
            command = vartype + "(" + value + ")"
            valuelist.append(eval(command))

    return valuelist


def create_points(bm, points):
    '''Create UGVerts and bmesh vertices from points coordinate list'''

    for i in range(0, len(points), 3):
        x = points[i]
        y = points[i+1]
        z = points[i+2]
        ug.UGVertex()
        bm.verts.new([x, y, z])
        if i % print_interval == 0:
            l.debug("... processed vertex count: %d" % i)

    bm.verts.ensure_lookup_table()
    bm.verts.index_update()
    l.debug("Number of vertices: %d" % (i/3 + 1))


def vtu_datalists_to_ugdata(connectivities, offsets, celltypes, cellfaces, cellfaceoffsets):
    '''Generate UGFaces and UGCells from VTU datalists'''

    conn_index = 0 # index for connectivities
    offset_index = 0 # index for cellfaces offset
    facemap = dict() # dictionary to map from vertex list string to UGFace index

    # Loop through all cells
    for ci in range(len(celltypes)):
        vtk_cell_type = celltypes[ci]
        conn_end = offsets[ci]
        vilist = connectivities[conn_index:conn_end] # Vertex index list
        if fulldebug: l.debug("Cell %d vertices: " % ci + str(vilist))

        # Polyhedron faces are specified by data in separate cellfaces list
        if vtk_cell_type == 42:
            faceoffset = cellfaceoffsets[ci] + 1
            polyfacelist = cellfaces[offset_index:faceoffset]
            offset_index = cellfaceoffsets[ci]
        else:
            polyfacelist = []

        facemap = vtu_add_cell(vtk_cell_type, vilist, facemap, polyfacelist)
        conn_index += conn_end - conn_index # Increment connectivities index

        if ci % print_interval == 0:
            l.debug("... processed cell count: %d" % ci)

def vtu_add_cell(vtk_cell_type, vilist, facemap, polyfacelist):
    '''Add new cell of argument type number and vertex index list. New
    faces are added to face map
    '''

    def add_cell_faces(c, fis, vilist, facemap, is_polyhedron=False):
        '''Create and/or add faces to cell c using face index list (fis) and
        vertex indices in vilist. If cell is polyhedron, then fis contains
        real vertex indices. Otherwise vertex list is mapped to real vertices.
        '''
        for fisverts in fis:
            if is_polyhedron:
                real_vilist = fisverts
            else:
                real_vilist = [vilist[v] for v in fisverts] # Actual vertex indices
            string = get_vert_string(real_vilist) # Get facemap key

            # Create new UGFace or use existing. Map to owner/neighbour.
            # If ugf is new, add to facemap.
            if string in facemap:
                ugf = facemap[string]
                ugf.neighbour = c
            else:
                ugf = ug.UGFace(real_vilist)
                ugf.owner = c
                facemap[string] = ugf
            # Add to cell
            c.add_face_and_verts(ugf)
        return facemap


    def get_polyhedron_fis(polyfacelist):
        '''Generate face face indices (fis) from argument polyhedron face list'''
        nFaces = polyfacelist[0] # First number is number of faces
        # status specifies type of next number: True=numVerts, False=vert index
        status = True
        fis = [] # list of vertex index lists, to be generated here
        for i in range(1, len(polyfacelist)):
            n = polyfacelist[i]
            if status:
                numVerts = n
                status = False
                vertlist = []
            else:
                vertlist.append(n)
            if len(vertlist) == numVerts:
                fis.append(vertlist)
                status = True
        if nFaces != len(fis):
            raise ValueError("Polyhedron faces list is broken: %s" % str(polyfacelist))
        return fis

    # Create new cell, and depending on VTK cell type, add faces
    c = ug.UGCell()

    if vtk_cell_type == 10: # VTK_TETRA
        fis = [[0,2,1], [0,1,3], [1,2,3], [0,3,2]]
        facemap = add_cell_faces(c, fis, vilist, facemap)
        if fulldebug: l.debug("Created cell %d: tetra" % c.ii)

    elif vtk_cell_type == 12: # VTK_HEXAHEDRON
        # Need to invert face loop direction for hex to get normals point out
        # fis = [[0,1,2,3], [0,4,5,1], [1,5,6,2], [2,6,7,3], [3,7,4,0], [7,6,5,4]]
        fis = [[0,3,2,1], [0,1,5,4], [1,2,6,5], [2,3,7,6], [3,0,4,7], [7,4,5,6]]
        facemap = add_cell_faces(c, fis, vilist, facemap)
        if fulldebug: l.debug("Created cell %d: hex" % c.ii)

    elif vtk_cell_type == 13: # VTK_WEDGE (=prism)
        fis = [[0,1,2], [0,3,4,1], [1,4,5,2], [2,5,3,0], [3,5,4]]
        facemap = add_cell_faces(c, fis, vilist, facemap)
        if fulldebug: l.debug("Created cell %d: prism" % c.ii)

    elif vtk_cell_type == 14: # VTK_PYRAMID
        fis = [[0,3,2,1], [0,4,3], [3,4,2], [2,4,1], [1,4,0]]
        facemap = add_cell_faces(c, fis, vilist, facemap)
        if fulldebug: l.debug("Created cell %d: pyramid" % c.ii)

    elif vtk_cell_type == 15: # VTK_PENTAGONAL_PRISM
        fis = [[0,1,2,3,4], [0,5,6,1], [1,6,7,2], [2,7,8,3], [3,8,9,4], [4,9,5,0], [9,8,7,6,5]]
        facemap = add_cell_faces(c, fis, vilist, facemap)
        if fulldebug: l.debug("Created cell %d: pentaprism" % c.ii)

    elif vtk_cell_type == 16: # VTK_HEXAGONAL_PRISM
        fis = [[0,1,2,3,4,5], [0,6,7,1], [1,7,8,2], [2,8,9,3], [3,9,10,4], [4,10,11,5], [5,11,6,0], [11,10,9,8,7,6]]
        facemap = add_cell_faces(c, fis, vilist, facemap)
        if fulldebug: l.debug("Created cell %d: hexaprism" % c.ii)

    elif vtk_cell_type == 42: # VTK_POLYHEDRON
        fis = get_polyhedron_fis(polyfacelist)
        if fulldebug: l.debug("Polyhedron fis: %s" % str(fis))
        facemap = add_cell_faces(c, fis, vilist, facemap, True)
        if fulldebug: l.debug("Created cell %d: polyhedron" % c.ii)

    else:
        raise ValueError("Unsupported VTK cell type %d" % vtk_cell_type)

    return facemap


def get_vert_string(vilist):
    '''Return ordered vertex index list converted to a string'''

    sortlist = list(vilist)
    sortlist.sort()
    string = ""
    for i in sortlist:
        string += str(i) + ","
    return string


def create_boundary_faces(bm):
    '''Create mesh faces for all boundary UGFaces'''

    bm.verts.ensure_lookup_table()
    bm.verts.index_update()
    fi = 0 # face index
    for ugf in ug.ugfaces:
        if not ugf.is_boundary_face():
            continue
        vilist = [bm.verts[v.bi] for v in ugf.ugverts]
        f = bm.faces.new(vilist)
        f.normal_update()
        ugf.add_mesh_face(fi)
        fi += 1

    return bm


##################
##### EXPORT #####
##################


class UG_OT_ExportVtu(bpy.types.Operator, ExportHelper):
    '''Export UG Data as Vtk Vtu Files'''
    bl_idname = "unstructured_grids.export_vtu"
    bl_label = "Export VTK Unstructured Grid (.vtu) (UG)"
    filename_ext = ".vtu"

    @classmethod
    def poll(cls, context):
        return context.mode in {'OBJECT','EDIT_MESH'} and ug.exists_ug_state()

    def execute(self, context):
        ug.update_ug_all_from_blender(self)
        write_vtu(self)
        return {'FINISHED'}


def write_vtu(self):
    '''Write unstuctured grid into VTU file format'''

    l.debug("Generating points")
    points, points_min, points_max, nPoints = generate_points_text()
    l.debug("Generating connectivities")
    connectivities = generate_connectivities_text()
    l.debug("Generating cell types and offsets")
    celltypes, offsets, offsets_max, nCells = generate_types_offsets_text()
    l.debug("Generating faces and faceoffsets")
    cellfaces, cellfaces_max, cellfaceoffsets = generate_cellfaces_text()
    text = generate_vtu_text(points, points_min, points_max, nPoints, \
                             connectivities, celltypes, offsets, \
                             offsets_max, nCells, \
                             cellfaces, cellfaces_max, cellfaceoffsets)
    filepath = self.filepath
    l.debug("Writing to: %s" % filepath)

    with open(filepath, 'w') as outfile:
        outfile.write(text)

    self.report({'INFO'}, "Exported %d cells to  %r" % (nCells, filepath))
    return None


def generate_points_text():
    '''Generate text for VTU points data'''

    points = ""
    n = 0
    points_min = 0.0 # not needed?
    points_max = 0.0 # not needed?
    ob = ug.get_ug_object()
    for ugv in ug.ugverts:
        if ugv.deleted:
            continue
        # Update export index
        ugv.ei = n
        v = ob.data.vertices[ugv.bi]
        points += "%.6g" % v.co.x + " " \
                + "%.6g" % v.co.y + " " \
                + "%.6g" % v.co.z + "\n"
        n += 1
    return points, points_min, points_max, n


def generate_connectivities_text():
    '''Generate text for VTU connectivity data'''

    connectivities = ""
    for c in ug.ugcells:
        if c.deleted:
            continue
        text = ""
        for ugv in c.ugverts:
            text += str(ugv.ei) + " "
        connectivities += text + "\n"
    return connectivities


def generate_types_offsets_text():
    '''Generate texts for VTU types and offsets'''

    # Simple implementation, generates only polyhedrons (type 42).
    # I wonder if there is downside to this compared to generating
    # traditional geometry elements (tetras, hexes etc.) where
    # possible..
    typeslist = []
    offsetlist = []
    nVert = 0
    nCells = 0
    for c in ug.ugcells:
        if c.deleted:
            continue
        typeslist.append(42)
        nVert += len(c.ugverts)
        offsetlist.append(nVert)
        nCells += 1
    # Convert from integer lists to space separated text
    celltypes = " ".join(map(str, typeslist)) + "\n"
    offsets = " ".join(map(str, offsetlist)) + "\n"
    return celltypes, offsets, offsetlist[-1], nCells


def generate_cellfaces_text():
    '''Generate texts for VTU polyhedron faces and faceoffsets'''

    cellfaces = ""
    cellfaceoffsets = ""
    offset = 0
    for c in ug.ugcells:
        faceslist = [len(c.ugfaces)] # Number of faces comes first
        if c.deleted:
            continue
        for ugf in c.ugfaces:
            faceslist.append(len(ugf.ugverts)) # Number of vertices per face
            for ugv in ugf.ugverts:
                faceslist.append(ugv.ei)
        cellfaces += " ".join(map(str, faceslist)) + "\n"
        cellfaceoffsets += str(offset + len(faceslist)) + " "
        offset += len(faceslist)
    return cellfaces, offset, cellfaceoffsets + "\n"


def generate_vtu_text(points, points_min, points_max, nPoints, \
                      connectivities, celltypes, offsets,
                      offsets_max, nCells, \
                      cellfaces, cellfaces_max, cellfaceoffsets):
    '''Embed generated data strings to vtu text format'''

    # Header
    text = '''<VTKFile type="UnstructuredGrid" version="1.0" byte_order="LittleEndian" header_type="UInt64">
  <UnstructuredGrid>
    <Piece NumberOfPoints="'''
    text += str(nPoints) + "\" NumberOfCells=\"" + \
            str(nCells) + '''">
      <PointData>
      </PointData>
      <CellData>
      </CellData>
      <Points>
        <DataArray type="Float32" Name="Points" NumberOfComponents="3" format="ascii" RangeMin="'''
    text += str(points_min) +"\" RangeMax=\"" + \
            str(points_max) +"\">\n"
    text += points
    text += '''       </DataArray>
      </Points>
      <Cells>
        <DataArray type="Int64" Name="connectivity" format="ascii" RangeMin="0" RangeMax="'''
    text += str(nPoints - 1) + "\">\n"
    text += connectivities
    text += '''        </DataArray>
        <DataArray type="Int64" Name="offsets" format="ascii" RangeMin="0" RangeMax="'''
    text += str(offsets_max) + "\">\n"
    text += offsets
    text += '''        </DataArray>
        <DataArray type="UInt8" Name="types" format="ascii" RangeMin="0" RangeMax="'''
    text += "42\">\n"
    text += celltypes
    text += '''        </DataArray>
        <DataArray type="Int64" Name="faces" format="ascii" RangeMin="0" RangeMax="'''
    text += str(nPoints) + "\">\n"
    text += cellfaces
    text += '''        </DataArray>
        <DataArray type="Int64" Name="faceoffsets" format="ascii" RangeMin="0" RangeMax="'''
    text += str(cellfaces_max) +"\">\n"
    text += cellfaceoffsets
    text += '''        </DataArray>
      </Cells>
    </Piece>
  </UnstructuredGrid>
</VTKFile>
'''
    return text
