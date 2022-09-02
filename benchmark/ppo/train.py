import argparse
import sys

import numpy as np

sys.path.append('../../')
from agent import PPOAgent
from atari_config import atari_config
from atari_model import AtariModel
from env_utils import LocalEnv, ParallelEnv
from storage import RolloutStorage

from rltoolkit.policy.modelfree.ppov2 import PPO
from rltoolkit.utils import logger, tensorboard


# Runs policy until 'real done' and returns episode reward
# A fixed seed is used for the eval environment
def run_evaluate_episodes(agent, eval_env, eval_episodes):
    eval_episode_rewards = []
    while len(eval_episode_rewards) < eval_episodes:
        obs = eval_env.reset()
        done = False
        while not done:
            action = agent.predict(obs)
            obs, reward, done, info = eval_env.step(action)
        if 'episode' in info.keys():
            eval_reward = info['episode']['r']
            eval_episode_rewards.append(eval_reward)
    return np.mean(eval_episode_rewards)


def main():
    config = atari_config
    if args.env_num:
        config['env_num'] = args.env_num
    config['env'] = args.env
    config['seed'] = args.seed
    config['test_every_steps'] = args.test_every_steps

    config['batch_size'] = int(config['env_num'] * config['step_nums'])
    config['num_updates'] = int(config['train_total_steps'] //
                                config['batch_size'])

    print(config)
    logger.info('------------------- PPO ---------------------')
    logger.info('Env: {}, seed: {}'.format(config['env'], config['seed']))
    logger.info('---------------------------------------------')
    logger.set_dir('./train_logs/{}_{}'.format(config['env'], config['seed']))

    envs = ParallelEnv(config)
    eval_env = LocalEnv(config['env'], test=True)

    obs_space = eval_env.obs_space
    act_space = eval_env.act_space

    model = AtariModel(obs_space, act_space)
    ppo = PPO(
        model,
        clip_param=config['clip_param'],
        entropy_coef=config['entropy_coef'],
        initial_lr=config['initial_lr'],
        continuous_action=config['continuous_action'])
    agent = PPOAgent(ppo, config)

    rollout = RolloutStorage(config['step_nums'], config['env_num'], obs_space,
                             act_space)

    obs = envs.reset()
    done = np.zeros(config['env_num'], dtype='float32')

    test_flag = 0
    total_steps = 0
    for update in range(1, config['num_updates'] + 1):
        for step in range(0, config['step_nums']):
            total_steps += 1 * config['env_num']

            value, action, logprob, _ = agent.sample(obs)
            print(value, action, logprob, _)
            next_obs, reward, next_done, info = envs.step(action)
            rollout.append(obs, action, logprob, reward, done, value.flatten())
            obs, done = next_obs, next_done

            for k in range(config['env_num']):
                if done[k] and 'episode' in info[k].keys():
                    logger.info(
                        'Training: total steps: {}, episode rewards: {}'.
                        format(total_steps, info[k]['episode']['r']))
                    tensorboard.add_scalar('train/episode_reward',
                                           info[k]['episode']['r'],
                                           total_steps)

        # Bootstrap value if not done
        value = agent.value(obs)
        rollout.compute_returns(value, done)

        # Optimizing the policy and value network
        v_loss, pg_loss, entropy_loss, lr = agent.learn(rollout)

        if total_steps // config['test_every_steps'] >= test_flag:
            while total_steps // config['test_every_steps'] >= test_flag:
                test_flag += 1

            if config['continuous_action']:
                # set running mean and variance of obs
                ob_rms = envs.eval_ob_rms
                eval_env.env.set_ob_rms(ob_rms)

            avg_reward = run_evaluate_episodes(agent, eval_env,
                                               config['eval_episode'])
            tensorboard.add_scalar('eval/episode_reward', avg_reward,
                                   total_steps)
            logger.info('Evaluation over: {} episodes, Reward: {}'.format(
                config['eval_episode'], avg_reward))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--env',
        type=str,
        default='PongNoFrameskip-v4',
        help='OpenAI gym environment name')
    parser.add_argument(
        '--seed', type=int, default=None, help='seed of the experiment')
    parser.add_argument(
        '--env_num', type=int, default=1, help='number of the environment.')
    parser.add_argument(
        '--continuous_action',
        action='store_true',
        default=False,
        help='action type of the environment')
    parser.add_argument(
        '--test_every_steps',
        type=int,
        default=int(5e3),
        help='the step interval between two consecutive evaluations')

    args = parser.parse_args()
    main()
