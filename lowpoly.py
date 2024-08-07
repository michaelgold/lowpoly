import bpy
import random
import time
import typer
from pathlib import Path
import addon_utils

app = typer.Typer()


def enable_3d_printing_addon():
    addon_utils.enable("object_print3d_utils")


def set_smooth_shading(obj):
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.shade_smooth()


def import_fbx(file_path):
    bpy.ops.import_scene.fbx(filepath=file_path)


def import_glb(file_path):
    bpy.ops.import_scene.gltf(filepath=file_path)


def import_obj(file_path):
    bpy.ops.wm.obj_import(filepath=file_path)


def import_usdz(file_path):
    bpy.ops.wm.usd_import(filepath=file_path)


def create_vertex_color_material(obj):
    mat = bpy.data.materials.new(name="VertexColorMaterial")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    # Clear default nodes
    nodes.clear()

    # Create nodes
    node_vertex_color = nodes.new(type="ShaderNodeVertexColor")
    node_bsdf = nodes.new(type="ShaderNodeBsdfPrincipled")
    node_output = nodes.new(type="ShaderNodeOutputMaterial")

    # Link nodes
    links.new(node_vertex_color.outputs[0], node_bsdf.inputs["Base Color"])
    links.new(node_bsdf.outputs[0], node_output.inputs[0])

    # Assign material to object
    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)

    return mat


def find_first_mesh():
    for obj in bpy.context.scene.objects:
        if obj.type == "MESH":
            return obj
    return None


@app.command()
def execute(
    file_path: str,
    source_object_name: str = "",
    target_faces: int = 7500,
    texture_resolution: int = 2048,
    multiresolution_levels: int = 3,
    voxel_size_factor: float = 0.01,
    voxel_remesh_iterations: int = 1,
    cleanup_threshold: float = 0.001,
    keep_vertex_colors: bool = False,
):
    start_time = time.time()

    # Delete the default cube
    if "Cube" in bpy.data.objects:
        bpy.data.objects["Cube"].select_set(True)
        bpy.ops.object.delete()

    enable_3d_printing_addon()

    # Get current script path
    script_path = Path(__file__).parent
    file_path = str(script_path / file_path)

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

    # If source_object_name is not specified, find the first mesh in the scene
    if not source_object_name:
        source_object = find_first_mesh()
        if not source_object:
            raise ValueError("No mesh found in the scene")
        source_object_name = source_object.name
    else:
        source_object = bpy.data.objects[source_object_name]

    print(f"Working with mesh: {source_object_name}")
    print(source_object)

    set_smooth_shading(source_object)

    # Calculate object height and normalized voxel size
    bbox = source_object.bound_box
    object_height = max(vertex[2] for vertex in bbox) - min(
        vertex[2] for vertex in bbox
    )
    normalized_voxel_size = object_height * voxel_size_factor

    print(f"Object height: {object_height}")
    print(f"Normalized voxel size: {normalized_voxel_size}")

    # Duplicate source object
    bpy.ops.object.select_all(action="DESELECT")
    source_object.select_set(True)
    bpy.context.view_layer.objects.active = source_object
    bpy.ops.object.duplicate()
    target_object = bpy.context.active_object

    # Use Volume to Mesh to create a manifold mesh
    bpy.ops.object.select_all(action="DESELECT")
    target_object.select_set(True)
    bpy.context.view_layer.objects.active = target_object

    # Add a Remesh modifier
    remesh_modifier = target_object.modifiers.new(name="Remesh", type="REMESH")
    remesh_modifier.mode = "VOXEL"
    remesh_modifier.voxel_size = normalized_voxel_size

    # Apply the Remesh modifier
    for _ in range(voxel_remesh_iterations):
        bpy.ops.object.modifier_apply(modifier="Remesh")
        if _ < voxel_remesh_iterations - 1:
            remesh_modifier = target_object.modifiers.new(name="Remesh", type="REMESH")
            remesh_modifier.mode = "VOXEL"
            remesh_modifier.voxel_size = normalized_voxel_size

    # Enter edit mode
    bpy.ops.object.mode_set(mode="EDIT")

    # Select all vertices
    bpy.ops.mesh.select_all(action="SELECT")

    # Recalculate normals to ensure consistency
    bpy.ops.mesh.normals_make_consistent(inside=False)

    # Merge vertices by distance
    bpy.ops.mesh.remove_doubles(threshold=cleanup_threshold)

    # Optional: Fill holes
    bpy.ops.mesh.fill_holes(sides=0)

    # Return to object mode
    bpy.ops.object.mode_set(mode="OBJECT")

    # Check if the mesh is manifold
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="DESELECT")
    bpy.ops.mesh.select_non_manifold()

    non_manifold_verts = sum(v.select for v in target_object.data.vertices)

    if non_manifold_verts > 0:
        print(
            f"Warning: {non_manifold_verts} non-manifold vertices found after cleanup."
        )
    else:
        print("Mesh is manifold.")

    bpy.ops.object.mode_set(mode="OBJECT")

    # Use quad remesher
    bpy.ops.object.quadriflow_remesh(target_faces=target_faces)

    # Check the result
    quad_count = sum(1 for p in target_object.data.polygons if len(p.vertices) == 4)
    total_faces = len(target_object.data.polygons)
    quad_percentage = (quad_count / total_faces) * 100 if total_faces > 0 else 0

    print(f"Quad faces: {quad_count}")
    print(f"Total faces: {total_faces}")
    print(f"Percentage of quad faces: {quad_percentage:.2f}%")

    # Shade the target mesh smooth
    set_smooth_shading(target_object)

    # Smart UV Project with specified island margin
    bpy.context.view_layer.objects.active = target_object
    bpy.ops.object.editmode_toggle()
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(island_margin=0.02)
    bpy.ops.object.editmode_toggle()

    # Add multiresolution modifier and subdivide
    multires = target_object.modifiers.new(name="Multires", type="MULTIRES")

    # Subdivide specified number of times
    for i in range(multiresolution_levels):
        bpy.ops.object.multires_subdivide(modifier="Multires", mode="CATMULL_CLARK")

    # Add shrinkwrap modifier
    shrinkwrap = target_object.modifiers.new(name="Shrinkwrap", type="SHRINKWRAP")
    shrinkwrap.target = source_object
    shrinkwrap.wrap_method = "PROJECT"
    shrinkwrap.project_limit = 0.005

    # Check if the object has vertex colors
    has_vertex_colors = len(target_object.data.vertex_colors) > 0

    # Check if the object has any materials, if not, create a new one
    if len(target_object.data.materials) == 0:
        if has_vertex_colors and keep_vertex_colors:
            new_mat = create_vertex_color_material(target_object)
        else:
            new_mat = bpy.data.materials.new(name="New Material")
            new_mat.use_nodes = True
            target_object.data.materials.append(new_mat)
    else:
        # Duplicate material
        original_mat = target_object.data.materials[0]
        new_mat = original_mat.copy()
        target_object.data.materials[0] = new_mat

    # If not using vertex colors, we need to create and bake textures
    if not keep_vertex_colors:
        # Create new textures
        number = random.randint(1000, 9999)
        diffuse_img = bpy.data.images.new(
            name=f"Diffuse_{number}",
            width=texture_resolution,
            height=texture_resolution,
        )
        normal_img = bpy.data.images.new(
            name=f"Normals_{number}",
            width=texture_resolution,
            height=texture_resolution,
        )
        print(normal_img)

        # Add the image texture nodes, connect them, and set them to the newly created images
        new_mat_node_tree = new_mat.node_tree
        bsdf_node = new_mat_node_tree.nodes.get("Principled BSDF")
        if not bsdf_node:
            bsdf_node = new_mat_node_tree.nodes.new(type="ShaderNodeBsdfPrincipled")

        diffuse_node = new_mat_node_tree.nodes.new(type="ShaderNodeTexImage")
        diffuse_node.image = diffuse_img

        normal_node = new_mat_node_tree.nodes.new(type="ShaderNodeTexImage")
        normal_node.image = normal_img
        normal_map_node = new_mat_node_tree.nodes.new(type="ShaderNodeNormalMap")

        # Apply shrinkwrap
        bpy.ops.object.select_all(action="DESELECT")
        target_object.select_set(True)
        bpy.ops.object.modifier_apply(modifier="Shrinkwrap")

        # Set render engine to cycles
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

        # Set the render samples to 2
        bpy.context.scene.cycles.samples = 2

        bpy.ops.object.bake(type="DIFFUSE")
        bpy.ops.image.pack()

        # Link nodes
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

    # Delete high poly source object
    bpy.ops.object.select_all(action="DESELECT")
    source_object.select_set(True)
    bpy.ops.object.delete()

    # Export the glb file
    bpy.ops.export_scene.gltf(
        filepath=Path(file_path).stem + ".glb",
        export_format="GLB",
        export_image_format="AUTO",
        export_draco_mesh_compression_enable=False,
    )

    end_time = time.time()
    execution_time = end_time - start_time
    print(f"Total execution time: {execution_time:.2f} seconds")

    # Clean up
    bpy.ops.wm.read_factory_settings()

    return {"FINISHED"}


if __name__ == "__main__":
    app()
