import bpy
import random

import typer
from pathlib import Path
import addon_utils

app = typer.Typer()


def enable_3d_printing_addon():
    # bpy.ops.wm.addon_enable(module="3d_print_tools")
    addon_utils.enable("object_print3d_utils")


def set_smooth_shading(obj):
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    #        obj.data.polygons.foreach_set('use_smooth',  [True] * len(obj.data.polygons))
    #        bpy.context.object.data.update()
    bpy.ops.object.shade_smooth()


def import_fbx(file_path):
    bpy.ops.import_scene.fbx(filepath=file_path)


def import_glb(file_path):
    bpy.ops.import_scene.gltf(filepath=file_path)


def import_obj(file_path):
    bpy.ops.import_scene.obj(filepath=file_path)


def import_usdz(file_path):
    bpy.ops.wm.usd_import(filepath=file_path)


@app.command()
def execute(
    file_path: str,
    source_object_name: str = "Mesh",
    target_faces: int = 7500,
    texture_resolution: int = 2048,
    multiresolution_levels: int = 3,
):
    # Delete the default cube
    bpy.data.objects["Cube"].select_set(True)
    bpy.ops.object.delete()

    enable_3d_printing_addon()
    # Extract values from the scene properties

    # Import the file
    if file_path.endswith(".fbx"):
        import_fbx(file_path)
    elif file_path.endswith(".glb"):
        import_glb(file_path)
    elif file_path.endswith(".obj"):
        import_obj(file_path)
    elif file_path.endswith(".usdz"):
        import_usdz(file_path)
    else:
        raise ValueError("Invalid file format")

    source_object = bpy.data.objects[source_object_name]
    print(source_object)

    set_smooth_shading(source_object)

    # Duplicate source object

    bpy.ops.object.select_all(action="DESELECT")
    source_object.select_set(True)
    bpy.context.view_layer.objects.active = source_object
    bpy.ops.object.duplicate()
    target_object = bpy.context.active_object.id_data

    # Use 3D-Print addon to make manifold
    bpy.ops.object.select_all(action="DESELECT")
    target_object.select_set(True)
    # Set the 3D view as the active area
    bpy.context.window.screen.areas[0].type = "VIEW_3D"
    bpy.context.view_layer.objects.active = target_object

    # Check if the active object is a mesh
    if target_object.type == "MESH":
        # Set mode to EDIT
        bpy.ops.object.mode_set(mode="EDIT")

        # Select all vertices
        bpy.ops.mesh.select_all(action="SELECT")

        bpy.ops.mesh.print3d_clean_non_manifold()

        # Set mode back to OBJECT
        bpy.ops.object.mode_set(mode="OBJECT")
    else:
        print("Active object is not a mesh")

    # Use quad remesher (assuming you have this operator from an addon)
    bpy.ops.object.quadriflow_remesh(target_faces=target_faces)

    # shade the target mesh smooth
    set_smooth_shading(target_object)

    # Smart UV Project with specified island margin
    bpy.context.view_layer.objects.active = target_object
    bpy.ops.object.editmode_toggle()
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(island_margin=0.02)

    bpy.ops.object.editmode_toggle()

    # Add multiresolution modifier and subdivide
    multires = target_object.modifiers.new(name="Multires", type="MULTIRES")

    # subdivide specified number of times
    for i in range(multiresolution_levels):
        bpy.ops.object.multires_subdivide(modifier="Multires", mode="CATMULL_CLARK")

    #       bpy.ops.object.modifier_apply({"object": target_object}, modifier=multires.name)

    # Add shrinkwrap modifier
    shrinkwrap = target_object.modifiers.new(name="Shrinkwrap", type="SHRINKWRAP")
    shrinkwrap.target = source_object
    shrinkwrap.wrap_method = "PROJECT"
    shrinkwrap.project_limit = 0.005

    # Duplicate material and create new textures
    original_mat = target_object.data.materials[0]
    new_mat = original_mat.copy()
    target_object.data.materials[0] = new_mat

    # Create new textures
    number = random.randint(1000, 9999)
    diffuse_img = bpy.data.images.new(
        name=f"Diffuse_{number}", width=texture_resolution, height=texture_resolution
    )
    normal_img = bpy.data.images.new(
        name=f"Normals_{number}", width=texture_resolution, height=texture_resolution
    )
    print(normal_img)

    # Add the image texture nodes, connect them, and set them to the newly created images
    new_mat_node_tree = new_mat.node_tree
    bsdf_node = [
        node for node in new_mat_node_tree.nodes if node.type == "BSDF_PRINCIPLED"
    ][0]

    diffuse_node = new_mat_node_tree.nodes.new(type="ShaderNodeTexImage")
    diffuse_node.image = diffuse_img

    normal_node = new_mat_node_tree.nodes.new(type="ShaderNodeTexImage")
    normal_node.image = normal_img
    normal_map_node = new_mat_node_tree.nodes.new(type="ShaderNodeNormalMap")

    # Apply shrinkwrap
    bpy.ops.object.select_all(action="DESELECT")
    target_object.select_set(True)
    bpy.ops.object.modifier_apply(modifier="Shrinkwrap")

    # set render engine to cycles
    bpy.context.scene.render.engine = "CYCLES"
    bpy.context.scene.cycles.device = "GPU"

    # Select source and target objects for baking
    bpy.ops.object.select_all(action="DESELECT")
    target_object.select_set(True)
    target_object.modifiers["Multires"].levels = 1

    # Bake normals
    bpy.context.scene.render.use_bake_multires = True
    print(new_mat_node_tree)
    new_mat_node_tree.nodes.active = normal_node
    print(new_mat_node_tree.nodes.active.image)
    print(bpy.context.view_layer.objects.active)
    bpy.context.scene.cycles.bake_type = "NORMAL"

    normal_node.image.colorspace_settings.name = "Non-Color"
    bpy.ops.object.bake_image()
    bpy.ops.image.pack()

    bpy.ops.object.select_all(action="DESELECT")
    source_object.select_set(True)
    target_object.select_set(True)

    # Bake diffuse
    bpy.context.scene.render.bake.use_selected_to_active = True
    bpy.context.scene.render.bake.use_cage = True
    bpy.context.scene.render.bake.cage_extrusion = 0.05
    bpy.context.scene.render.bake.use_pass_direct = False
    bpy.context.scene.render.bake.use_pass_indirect = False
    bpy.context.scene.render.bake.use_pass_color = True
    new_mat_node_tree.nodes.active = diffuse_node
    print(f"Active image: {new_mat_node_tree.nodes.active.image}")
    print(f"Active node: {new_mat_node_tree.nodes.active}")
    bpy.context.scene.cycles.bake_type = "DIFFUSE"

    # set the render samplese to 2
    bpy.context.scene.cycles.samples = 2

    bpy.ops.object.bake(type="DIFFUSE")
    bpy.ops.image.pack()

    # link nodes
    new_mat_node_tree.links.new(
        diffuse_node.outputs["Color"], bsdf_node.inputs["Base Color"]
    )
    new_mat_node_tree.links.new(
        normal_node.outputs["Color"], normal_map_node.inputs["Color"]
    )
    new_mat_node_tree.links.new(
        normal_map_node.outputs["Normal"], bsdf_node.inputs["Normal"]
    )

    # Remove multires
    bpy.ops.object.select_all(action="DESELECT")
    target_object.select_set(True)
    bpy.ops.object.modifier_remove(modifier="Multires")

    # delete high poly source object
    bpy.ops.object.select_all(action="DESELECT")
    source_object.select_set(True)
    bpy.ops.object.delete()

    # export the glb file
    bpy.ops.export_scene.gltf(
        filepath=Path(file_path).stem + ".glb",
        export_format="GLB",
        export_image_format="AUTO",
        export_draco_mesh_compression_enable=False,
    )

    return {"FINISHED"}


if __name__ == "__main__":
    app()
