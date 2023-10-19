from sofa_env.scenes.rope_threading.rope_threading_env import RopeThreadingEnv, ObservationType, ActionType, RenderMode
import numpy as np
from sofa_env.utils.human_input import XboxController
from sofa_env.wrappers.trajectory_recorder import TrajectoryRecorder
from sofa_env.wrappers.realtime import RealtimeWrapper
import time
from collections import deque
import cv2
import argparse
from pathlib import Path
from typing import Tuple, Dict

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Setup human input behavior.")
    parser.add_argument("-rv", "--record_video", action="store_true", help="Record video of the trajectory.")
    parser.add_argument("-rt", "--record_trajectory", action="store_true", help="Record the full trajectory.")
    parser.add_argument("-re", "--randomize_eyes", action="store_true", help="Randomize the eye poses.")
    parser.add_argument("-i", "--info", action="store", type=str, help="Additional info to store in the metadata.")
    args = parser.parse_args()

    controller = XboxController()
    time.sleep(0.1)
    if not controller.is_alive():
        raise RuntimeError("Could not find Xbox controller.")

    image_shape = (1024, 1024)
    image_shape_to_save = (256, 256)
    eye_config = [
        (60, 10, 0, 90),
        (10, 10, 0, 90),
        (10, 60, 0, -45),
        (60, 60, 0, 90),
    ]
    create_scene_kwargs = {
        "eye_config": eye_config,
        "eye_reset_noise": {
            "low": np.array([-20.0, -20.0, 0.0, -15]),
            "high": np.array([20.0, 20.0, 0.0, 15]),
        }
        if args.randomize_eyes
        else None,
        "randomize_gripper": False,
        "randomize_grasp_index": False,
        "start_grasped": True,
    }

    env = RopeThreadingEnv(
        observation_type=ObservationType.RGB,
        render_mode=RenderMode.HUMAN,
        action_type=ActionType.CONTINUOUS,
        image_shape=image_shape,
        create_scene_kwargs=create_scene_kwargs,
        frame_skip=1,
        time_step=1 / 30,
        settle_steps=10,
        fraction_of_rope_to_pass=0.01,
        only_right_gripper=False,
        individual_agents=True,
    )

    env = RealtimeWrapper(env)

    if args.record_video:
        video_folder = Path("videos")
        video_folder.mkdir(exist_ok=True)
        video_name = time.strftime("%Y%m%d-%H%M%S")
        video_path = video_folder / f"{video_name}.mp4"
        video_writer = cv2.VideoWriter(
            str(video_path),
            cv2.VideoWriter_fourcc(*"mp4v"),
            1 / (env.time_step / env.frame_skip),
            image_shape[::-1],
        )
    else:
        video_writer = None

    if args.record_trajectory:

        def store_rgb_obs(self: TrajectoryRecorder, shape: Tuple[int, int] = image_shape_to_save):
            observation = self.env.render()
            observation = cv2.resize(
                observation,
                shape,
                interpolation=cv2.INTER_AREA,
            )
            self.trajectory["rgb"].append(observation)

        metadata = {
            "frame_skip": env.frame_skip,
            "time_step": env.time_step,
            "observation_type": env.observation_type.name,
            "reward_amount_dict": env.reward_amount_dict,
            "user_info": args.info,
        }

        env = TrajectoryRecorder(
            env,
            log_dir="trajectories",
            metadata=metadata,
            store_info=True,
            save_compressed_keys=["observation", "terminal_observation", "rgb", "info"],
            after_step_callbacks=[store_rgb_obs],
            after_reset_callbacks=[store_rgb_obs],
        )

    reset_obs, reset_info = env.reset()
    if video_writer is not None:
        video_writer.write(env.render()[:, :, ::-1])

    done = False

    instrument = 0
    up = True

    fps_list = deque(maxlen=100)

    while not done:
        start = time.perf_counter()
        lx, ly, rx, ry, lt, rt = controller.read()

        sample_action: Dict = env.action_space.sample()

        sample_action["left_gripper"][:] = 0.0
        sample_action["left_gripper"][0] = -lx
        sample_action["left_gripper"][1] = ly

        sample_action["right_gripper"][:] = 0.0
        sample_action["right_gripper"][0] = -rx
        sample_action["right_gripper"][1] = ry

        if controller.y:
            if up:
                instrument = 0 if instrument == 1 else 1
            up = False
        else:
            up = True

        action = sample_action["right_gripper"] if instrument == 0 else sample_action["left_gripper"]
        action[2] = controller.right_bumper - controller.left_bumper
        action[3] = rt - lt
        action[4] = controller.b - controller.a

        obs, reward, terminated, truncated, info = env.step(sample_action)
        done = terminated or truncated

        if video_writer is not None:
            video_writer.write(env.render()[:, :, ::-1])

        if controller.x:
            cv2.imwrite("exit_image.png", env.render()[:, :, ::-1])
            break

        end = time.perf_counter()
        fps = 1 / (end - start)
        fps_list.append(fps)
        print(f"FPS Mean: {np.mean(fps_list):.5f}    STD: {np.std(fps_list):.5f}")

    if video_writer is not None:
        video_writer.release()
