import os, sys, json, argparse
import traceback
import shutil
from pathlib import Path

WRAPPER_ROOT = os.path.dirname(__file__)
if WRAPPER_ROOT not in sys.path:
    sys.path.insert(0, WRAPPER_ROOT)

from Make_It_Animatable import app as mia

#app.py crashes if it tries to log to gradio
def _headless_log_message(message: str, level="info", duration=None, visible=True, **kwargs):
    if level in ("info", "success"):
        print(f"[Make-It-Animatable] {message}")
    elif level == "warning":
        print(f"[Make-It-Animatable WARNING] {message}")

import gradio.helpers
gradio.helpers.log_message = _headless_log_message

mia.init_models()
#app.py crashes if these files don't exist
data_dir = Path(WRAPPER_ROOT) / "Make_It_Animatable" / "data"
(data_dir / "Standard Run.fbx").touch()
examples_dir = data_dir / "examples"
examples_dir.mkdir(parents=True, exist_ok=True)
(examples_dir / "log.csv").touch()
mia.init_blocks()

import bpy

def fbx2glb(input_fbx: str, output_glb: str, original_glb: str = None, clear_scene=True):
    input_fbx = os.path.abspath(input_fbx)
    output_glb = os.path.abspath(output_glb)

    if clear_scene:
        bpy.ops.object.select_all(action='SELECT')
        bpy.ops.object.delete(use_global=False)

        for block in bpy.data.meshes:
            bpy.data.meshes.remove(block)

    # If we have the original GLB, import it first to preserve materials/textures
    if original_glb and os.path.exists(original_glb):
        original_glb = os.path.abspath(original_glb)
        bpy.ops.import_scene.gltf(filepath=original_glb)

        # Store original mesh objects to get their materials/textures
        original_meshes = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH']
        original_armatures = [obj for obj in bpy.context.scene.objects if obj.type == 'ARMATURE']

        # Store original materials from the GLB
        original_materials = {}  # Map from material name to material object
        for mesh in original_meshes:
            if mesh.data and hasattr(mesh.data, 'materials'):
                for mat in mesh.data.materials:
                    if mat:
                        original_materials[mat.name] = mat

        # Clear the scene to import FBX
        bpy.ops.object.select_all(action='SELECT')
        bpy.ops.object.delete(use_global=False)

        for block in bpy.data.meshes:
            bpy.data.meshes.remove(block)

        # Now import the FBX to get the properly rigged mesh and armature
        bpy.ops.import_scene.fbx(filepath=input_fbx, ignore_leaf_bones=True)

        # Get the FBX armature and mesh (these are properly aligned from auto-rigging)
        fbx_armatures = [obj for obj in bpy.context.scene.objects if obj.type == 'ARMATURE']
        fbx_meshes = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH']

        # Apply the original GLB materials to the FBX meshes
        for fbx_mesh in fbx_meshes:
            if fbx_mesh.data and hasattr(fbx_mesh.data, 'materials'):
                # Clear existing materials
                fbx_mesh.data.materials.clear()

                # Apply original materials - try to match by material name or just apply all if single mesh
                applied_any_material = False
                for orig_mat_name, orig_mat in original_materials.items():
                    # For now, apply the original materials to the FBX mesh
                    # This preserves the original PBR textures
                    fbx_mesh.data.materials.append(orig_mat)
                    applied_any_material = True

                # If no materials were applied (maybe names didn't match), keep existing ones
                if not applied_any_material and len(fbx_mesh.data.materials) == 0:
                    # If we have original materials but couldn't match, try applying any original material
                    if original_materials:
                        first_orig_mat = next(iter(original_materials.values()))
                        fbx_mesh.data.materials.append(first_orig_mat)

    else:
        # Fallback to original behavior if no original GLB is provided
        bpy.ops.import_scene.fbx(filepath=input_fbx, ignore_leaf_bones=True)

    # Apply transforms to all remaining objects
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH']
    armatures = [obj for obj in bpy.context.scene.objects if obj.type == 'ARMATURE']

    #bug in bpy glb format causes armature joint spheres to display HUGE if scale != 1
    bpy.ops.object.select_all(action='DESELECT')
    for arm in armatures:
        arm.select_set(True)
        bpy.context.view_layer.objects.active = arm
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

    bpy.ops.object.select_all(action='DESELECT')
    for mesh in meshes:
        mesh.select_set(True)
        bpy.context.view_layer.objects.active = mesh
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

    bpy.ops.export_scene.gltf(
        filepath=output_glb,
        export_format='GLB',
        export_extras=False
    )

    print(f"Converted:\n  {input_fbx}\n→ {output_glb}")

def run_once(input_path, db, **kwargs):
    list(mia._pipeline(input_path=str(input_path), db=db, **kwargs))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--kwargs", default="{}")
    args = parser.parse_args()

    try:
        kwargs = json.loads(args.kwargs)
        db = mia.DB()
        run_once(Path(args.input), db, **kwargs)
        output_dir = Path(os.path.join(os.path.dirname(args.input), os.path.splitext(os.path.basename(args.input))[0]))

        temp_files_to_delete = [
            db.joints_coarse_path,
            db.normed_path,
            db.sample_path,
            db.bw_path,
            db.joints_path,
            db.rest_lbs_path,
            db.rest_vis_path,
            db.anim_vis_path,
        ]

        for path in temp_files_to_delete:
            if path:
                try:
                    Path(path).unlink(missing_ok=True)
                except Exception:
                    pass

        input_path = Path(db.anim_path)
        output_path = Path(args.output)
        if input_path.suffix.lower() == '.fbx':
            # Pass the original input path to preserve original GLB data
            fbx2glb(db.anim_path, output_path, original_glb=args.input)
        else:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(input_path, output_path)

    except Exception as e:
        tb = traceback.format_exc()
        print(tb, file=sys.stderr)
        sys.exit(1)