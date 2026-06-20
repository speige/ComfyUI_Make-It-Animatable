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

    bpy.ops.wm.read_factory_settings(use_empty=True)

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

    bpy.ops.import_scene.fbx(filepath=input_fbx, ignore_leaf_bones=False)

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


    # When animation is present, object-level transforms can be keyframed.
    # We must remove these object-level animation tracks to preserve the pose-bone animations.
    # We clean all actions in bpy.data.actions to ensure NLA tracks and multiple actions are covered.
    for action in bpy.data.actions:
        fcurves_to_remove = [
            fcurve for fcurve in action.fcurves
            if not fcurve.data_path.startswith("pose.bones")
        ]
        for fcurve in fcurves_to_remove:
            action.fcurves.remove(fcurve)

        # Scale all bone location keyframes by 0.01 to match the baked armature scale
        for fcurve in action.fcurves:
            if fcurve.data_path.endswith(".location") or "location" in fcurve.data_path:
                for kp in fcurve.keyframe_points:
                    kp.co[1] *= 0.01
                    kp.handle_left[1] *= 0.01
                    kp.handle_right[1] *= 0.01

    # Stash all actions onto the armature's NLA tracks so they are exported to glTF/GLB
    armatures = [obj for obj in bpy.context.scene.objects if obj.type == 'ARMATURE']
    if armatures:
        arm = armatures[0]
        if not arm.animation_data:
            arm.animation_data_create()
        for track in list(arm.animation_data.nla_tracks):
            arm.animation_data.nla_tracks.remove(track)
        for action in list(bpy.data.actions):
            track = arm.animation_data.nla_tracks.new()
            track.name = action.name
            track.mute = True
            track.strips.new(action.name, int(action.frame_range[0]), action)
        if bpy.data.actions:
            arm.animation_data.action = list(bpy.data.actions)[0]

    # Apply location, rotation, and scale transforms to meshes and armatures
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH']
    armatures = [obj for obj in bpy.context.scene.objects if obj.type == 'ARMATURE']

    bpy.ops.object.select_all(action='DESELECT')
    for obj in meshes + armatures:
        obj.select_set(True)

    if bpy.context.selected_objects:
        bpy.context.view_layer.objects.active = bpy.context.selected_objects[0]
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

    # Delete unused materials and meshes to keep output GLB clean and avoid name collisions
    for mat in list(bpy.data.materials):
        if mat.users == 0:
            bpy.data.materials.remove(mat)
    for mesh in list(bpy.data.meshes):
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)

    bpy.ops.export_scene.gltf(
        filepath=output_glb,
        export_format='GLB',
        export_extras=False
    )

    print(f"Converted:\n  {input_fbx}\n-> {output_glb}")

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