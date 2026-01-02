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

def fbx2glb(input_fbx: str, output_glb: str, original_glb: str):
    input_fbx = os.path.abspath(input_fbx)
    output_glb = os.path.abspath(output_glb)

    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)

    # Get PBR from original GLB
    original_glb = os.path.abspath(original_glb)
    bpy.ops.import_scene.gltf(filepath=original_glb)
    original_meshes = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH']
    original_materials = {}
    for mesh in original_meshes:
        if mesh.data and hasattr(mesh.data, 'materials'):
            for mat in mesh.data.materials:
                if mat:
                    original_materials[mat.name] = mat

    # Clear the scene to import FBX
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)

    bpy.ops.import_scene.fbx(filepath=input_fbx, ignore_leaf_bones=True)

    # Get the auto-rigged mesh from FBX
    fbx_meshes = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH']

    # Apply the original GLB materials to the FBX meshes
    for fbx_mesh in fbx_meshes:
        if fbx_mesh.data and hasattr(fbx_mesh.data, 'materials'):
            fbx_mesh.data.materials.clear()

            applied_any_material = False
            for _, orig_mat in original_materials.items():
                fbx_mesh.data.materials.append(orig_mat)
                applied_any_material = True

            # If no materials were applied, keep existing ones
            if not applied_any_material and len(fbx_mesh.data.materials) == 0:
                if original_materials:
                    first_orig_mat = next(iter(original_materials.values()))
                    fbx_mesh.data.materials.append(first_orig_mat)


    # Apply transforms to all remaining objects
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH']
    armatures = [obj for obj in bpy.context.scene.objects if obj.type == 'ARMATURE']

    # When animation is present, object-level transforms can be keyframed.
    # We must remove these object-level animation tracks to correctly apply transforms,
    # while preserving the pose-bone animations.
    for obj in meshes + armatures:
        if obj.animation_data and obj.animation_data.action:
            action = obj.animation_data.action
            fcurves_to_remove = [
                fcurve for fcurve in action.fcurves
                if not fcurve.data_path.startswith("pose.bones")
            ]
            for fcurve in fcurves_to_remove:
                action.fcurves.remove(fcurve)

    #bug in blender import of glb format causes armature joint spheres to display HUGE if scale != 1
    bpy.ops.object.select_all(action='DESELECT')
    selection = meshes + armatures
    for obj in selection:
        obj.scale = (1.0, 1.0, 1.0)
        obj.select_set(True)

    if bpy.context.selected_objects:
        bpy.context.view_layer.objects.active = bpy.context.selected_objects[0]
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=False)

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