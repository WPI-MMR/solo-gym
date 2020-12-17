from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

import numpy as np
import pkg_resources
import pybullet as p
import pybullet_data as pbd
import pybullet_utils.bullet_client as bc
import random
import time

import gym
from gym import error, spaces

from gym_solo.core.configs import Solo8BaseConfig
from gym_solo.core import obs
from gym_solo.core import rewards
from gym_solo.core import termination as terms

from gym_solo import solo_types


@dataclass
class Solo8VanillaConfig(Solo8BaseConfig):
  urdf_path: str = 'assets/solo8v2/solo.urdf'


class Solo8VanillaEnv(gym.Env):
  """An unmodified solo8 gym environment.
  
  Note that the model corresponds to the solo8v2.
  """
  def __init__(self, use_gui: bool = False, realtime: bool = False, 
               config=None, **kwargs) -> None:
    """Create a solo8 env"""
    self._realtime = realtime
    self._config = config

    self.client = bc.BulletClient(
      connection_mode=p.GUI if use_gui else p.DIRECT)
    self.client.setAdditionalSearchPath(pbd.getDataPath())
    self.client.setGravity(*self._config.gravity)
    self.client.setPhysicsEngineParameter(fixedTimeStep=self._config.dt, 
                                          numSubSteps=1)

    self.plane = self.client.loadURDF('plane.urdf')
    self.robot, joint_cnt = self._load_robot()

    self.obs_factory = obs.ObservationFactory(self.client)
    self.reward_factory = rewards.RewardFactory()
    self.termination_factory = terms.TerminationFactory()

    self._zero_gains = np.zeros(joint_cnt)
    self.action_space = spaces.Box(-self._config.motor_torque_limit, 
                                   self._config.motor_torque_limit,
                                   shape=(joint_cnt,))
    
    self.reset(init_call=True)

  def step(self, action: List[float]) -> Tuple[solo_types.obs, float, bool, 
                                                Dict[Any, Any]]:
    """The agent takes a step in the environment.

    Args:
      action (List[float]): The torques applied to the motors in N•m. Note
        len(action) == the # of actuator

    Returns:
      Tuple[solo_types.obs, float, bool, Dict[Any, Any]]: A tuple of the next
        observation, the reward for that step, whether or not the episode 
        terminates, and an info dict for misc diagnostic details.
    """
    self.client.setJointMotorControlArray(self.robot, 
                                np.arange(self.action_space.shape[0]),
                                p.TORQUE_CONTROL, forces=action,
                                positionGains=self._zero_gains, 
                                velocityGains=self._zero_gains)
    self.client.stepSimulation()

    if self._realtime:
      time.sleep(self._config.dt)

    obs_values, obs_labels = self.obs_factory.get_obs()
    reward = self.reward_factory.get_reward()

    # TODO: Write tests for this call
    done = self.termination_factory.is_terminated()

    return obs_values, reward, done, {'labels': obs_labels}

  def reset(self, init_call: bool = False) -> solo_types.obs:
    """Reset the state of the environment and returns an initial observation.
    
    Returns:
      solo_types.obs: The initial observation of the space.
    """
    self.client.removeBody(self.robot)
    self.robot, _ = self._load_robot()

    # TODO: We need to change this to have the robot always be in home position
    # Let gravity do it's thing and reset the environment deterministically
    for i in range(1000):
      self.client.setJointMotorControlArray(
        self.robot, np.arange(self.action_space.shape[0]), 
        p.TORQUE_CONTROL, forces=self._zero_gains, 
        positionGains=self._zero_gains, velocityGains=self._zero_gains)
      self.client.stepSimulation()
    
    if init_call:
      return np.empty(shape=(0,)), []
    else:
      obs_values, _ = self.obs_factory.get_obs()
      return obs_values
  
  @property
  def observation_space(self):
    # TODO: Write tests for this function
    return self.obs_factory.get_observation_space()

  def _load_robot(self) -> Tuple[int, int]:
    """Load the robot from URDF and reset the dynamics.

    Returns:
        Tuple[int, int]: the id of the robot object and the number of joints.
    """
    robot_id = self.client.loadURDF(
      self._config.urdf, self._config.robot_start_pos, 
      self.client.getQuaternionFromEuler(
        self._config.robot_start_orientation_euler),
      flags=p.URDF_USE_INERTIA_FROM_FILE, useFixedBase=False)

    joint_cnt = self.client.getNumJoints(robot_id)
    self.client.setJointMotorControlArray(robot_id, np.arange(joint_cnt),
                                          p.VELOCITY_CONTROL, 
                                          forces=np.zeros(joint_cnt))

    for joint in range(joint_cnt):
      self.client.changeDynamics(robot_id, joint, 
                                 linearDamping=self._config.linear_damping, 
                                 angularDamping=self._config.angular_damping, 
                                 restitution=self._config.restitution, 
                                 lateralFriction=self._config.lateral_friction)

    return robot_id, joint_cnt

  def _close(self) -> None:
    """Soft shutdown the environment. """
    self.client.disconnect()

  def _seed(self, seed: int) -> None:
    """Set the seeds for random and numpy

    Args:
      seed (int): The seed to set
    """
    np.random.seed(seed)
    random.seed(seed)