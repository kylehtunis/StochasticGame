import numpy as np
import matplotlib.pyplot as plt
from tqdm import tqdm
from concurrent.futures import ProcessPoolExecutor
from engine import GameEngine
from facilities import Artillery, Helipad, ReconPlane
from pieces import RWTarget, Target
import ui
import pickle
from pathlib import Path
import sys
from collections import Counter
from scipy.stats import norm
ARTILLERY_COLOR = "#db3434"
HELICOPTER_COLOR = "#cdd331"
RECON_PLANE_COLOR = "#1818C3"

ui.ui_event_bridge.push_event = lambda *args, **kwargs: None


def build_game(difficulty, artillery_res, helipad_res, recon_res, seed=42):
    np.random.seed(seed)

    game = GameEngine(
        size=difficulty * 20,
        resource_limit=50,
        real_time=False,
        simulation_mode=True
    )

    # Pieces
    pieces = {}

    for speed, i in enumerate(range(100000, 100010)):
        posx, posy = game.random_pos()
        pieces[i] = RWTarget(i, posx, posy, game, 5, speed + 1)

    for i in range(100010, 100060):
        posx, posy = game.random_pos()
        pieces[i] = Target(i, posx, posy, game, 1)

    # Facilities
    facilities = {
        1: Artillery(1, artillery_res, game),
        2: Helipad(2, helipad_res, game, 0.5),
        3: ReconPlane(
            3,
            recon_res,
            game=game,
            n_strata=11 - (5 - difficulty) * 2
        ),
    }

    game.setup(pieces, facilities)
    return game


def run_single_simulation(difficulty, a, h, r, seed):
    game = build_game(difficulty, a, h, r, seed)
    game.run()
    return game.points


def run_parallel(difficulty, a, h, r, base_seed, n_sim, max_workers=None):
    """
    Executes n_sim simulations in parallel.
    Returns an array of final scores.
    """
    seeds = [base_seed + k for k in range(n_sim)]
    args = [(difficulty, a, h, r, s) for s in seeds]

    scores = []
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        # submit work
        futures = [executor.submit(run_single_simulation, *arg) for arg in args]

        # wrap in tqdm progress bar
        for f in tqdm(futures):
            scores.append(f.result())

    return np.array(scores)


def run_baseline_experiment(n_sim=1000, max_workers=None):
    results = {}
    conditions = {
        "artillery_only": (50, 0, 0),
        "helipad_only":   (0, 50, 0),
        "recon_only":     (0, 0, 50)
    }

    for difficulty in [1, 2]:
        for name, (a, h, r) in conditions.items():
            print(f"Running: difficulty={difficulty}, {name}")

            base_seed = 10_000_000 + difficulty * 10_000 + hash(name) % 10_000

            scores = run_parallel(
                difficulty=difficulty,
                a=a,
                h=h,
                r=r,
                base_seed=base_seed,
                n_sim=n_sim,
                max_workers=max_workers
            )

            results[(difficulty, name)] = {
                "mean": float(scores.mean()),
                "variance": float(scores.var(ddof=1)),
                "scores": scores
            }

    return results


def coarse_grid_sweep(difficulty=1, n_sim=200, max_workers=None):
    """
    Coarse grid sweep of (artillery, helipad, recon) resources in steps of 5,
    where a + h + r = 50. Runs n_sim simulations per combination.
    Saves results to pickle and prints top 10 combos by mean score.
    """
    resource_values = list(range(0, 51, 5))
    combos = [(a,h,r) for a in resource_values 
                        for h in resource_values 
                        for r in resource_values if a+h+r==50]

    results = {}

    for a,h,r in tqdm(combos, desc="Grid Sweep"):
        base_seed = 1_000_000 + a*1000 + h*100 + r*10
        scores = run_parallel(
            difficulty=difficulty,
            a=a,
            h=h,
            r=r,
            base_seed=base_seed,
            n_sim=n_sim,
            max_workers=max_workers
        )
        results[(a,h,r)] = {
            "mean": float(scores.mean()),
            "variance": float(scores.var(ddof=1)),
            "scores": scores
        }

    return results


def simulated_annealing(
    difficulty=1,
    n_sim=100,
    max_workers=None,
    initial_state=(20, 20, 10),
    T_init=10.0,
    T_min=0.1,
    alpha=0.95,
    max_iter=100,
    n_neighbors=5,
    seed=None
):
    """
    Parallelized simulated annealing
    """
    rng = np.random.default_rng(seed)
    cache = {}

    def energy(state):
        if state in cache:
            return -cache[state]
        a, h, r = state
        base_seed = 999_000 + a*1000 + h*100 + r*10
        scores = run_parallel(difficulty, a, h, r, base_seed, n_sim, max_workers)
        mean_score = scores.mean()
        cache[state] = mean_score
        return -mean_score  # negative for minimization

    def generate_neighbors(state):
        a, h, r = state
        neighbors = []
        values = np.array([a, h, r])
        for _ in range(n_neighbors):
            idxs = rng.choice(3, size=2, replace=False)
            neighbor_values = values.copy()
            if neighbor_values[idxs[0]] > 0:
                neighbor_values[idxs[0]] -= 1
                neighbor_values[idxs[1]] += 1
            neighbors.append(tuple(neighbor_values))
        return neighbors

    current = initial_state
    current_energy = energy(current)
    best = current
    best_energy = current_energy
    T = T_init
    progress = []

    for iteration in tqdm(range(max_iter), desc="Simulated Annealing"):
        neighbors = generate_neighbors(current)
        neighbor_energies = np.array([energy(n) for n in neighbors])
        min_idx = neighbor_energies.argmin()
        next_state = neighbors[min_idx]
        next_energy = neighbor_energies[min_idx]

        if next_energy < current_energy or rng.random() < np.exp((current_energy - next_energy) / T):
            current = next_state
            current_energy = next_energy
            if current_energy < best_energy:
                best = current
                best_energy = current_energy

        T = max(T * alpha, T_min)
        progress.append((-best_energy, best))

    return best, -best_energy, progress, cache


def gibbs_sampling(
    difficulty=1,
    n_sim=100,
    max_workers=None,
    initial_state=(20, 20, 10),
    n_iter=500,
    seed=None
):
    """
    Gibbs sampling for 3D resource allocation (a, h, r) with a + h + r = 50.
    """
    rng = np.random.default_rng(seed)
    cache = {}

    def mean_score(state):
        if state in cache:
            return cache[state]
        a, h, r = state
        base_seed = 999_000 + a*1000 + h*100 + r*10
        scores = run_parallel(difficulty, a, h, r, base_seed, n_sim, max_workers)
        cache[state] = scores.mean()
        return cache[state]

    def sample_conditional(i, current_state):
        """
        Sample one coordinate (i-th) conditioned on the sum constraint.
        i = 0 -> artillery, 1 -> helipad, 2 -> recon
        """
        total = 50
        other_indices = [j for j in range(3) if j != i]
        remaining = total - sum(current_state[j] for j in other_indices)

        # Gibbs: choose all possible values for i, compute unnormalized probabilities
        candidates = []
        probs = []
        for val in range(0, remaining + 1):
            new_state = list(current_state)
            new_state[i] = val
            candidates.append(tuple(new_state))
            probs.append(mean_score(tuple(new_state)))

        # convert mean scores to probabilities
        probs = np.array(probs)
        # normalize to probabilities (softmax)
        exp_probs = np.exp(probs - probs.max())  # subtract max for stability
        exp_probs /= exp_probs.sum()

        # sample new value
        chosen_idx = rng.choice(len(candidates), p=exp_probs)
        return candidates[chosen_idx]

    current = initial_state
    progress = []

    for iteration in tqdm(range(n_iter), desc="Gibbs Sampling 3D"):
        for i in range(3):
            current = sample_conditional(i, current)
        score = mean_score(current)
        progress.append((score, current))

    # find best allocation
    best_score, best_state = max(progress, key=lambda x: x[0])

    return best_state, best_score, progress, cache


def save_results(results, filename="sim_data/baseline_results.pkl"):
    path = Path(filename)
    with path.open("wb") as f:
        pickle.dump(results, f, protocol=pickle.HIGHEST_PROTOCOL)
    print(f"Saved results to {path.resolve()}")


def load_results(filename="sim_data/baseline_results.pkl"):
    with open(filename, "rb") as f:
        return pickle.load(f)


def plot_mean_scores(results, path):
    output_dir = Path(path)
    output_dir.mkdir(exist_ok=True)
    weapons = ["artillery_only", "helipad_only", "recon_only"]
    difficulties = [1, 2]

    bar_width = 0.35
    x = np.arange(len(weapons))

    plt.figure(figsize=(10,6))
    for i, difficulty in enumerate(difficulties):
        means = [results[(difficulty, w)]["mean"] for w in weapons]
        stds = [np.sqrt(results[(difficulty, w)]["variance"]) for w in weapons]
        plt.bar(x + i*bar_width, means, yerr=stds, capsize=5, width=bar_width,
                label=f"Difficulty {difficulty}")

    plt.xticks(x + bar_width/2, weapons)
    plt.ylabel("Mean Score")
    plt.title("Mean Score per Weapon with Standard Deviation")
    plt.legend()
    plt.grid(axis='y', linestyle='--', alpha=0.7)
    plt.tight_layout()
    plt.savefig(output_dir / "mean_score_bar.png")
    plt.close()


def plot_score_distributions(results, path):
    output_dir = Path(path)
    output_dir.mkdir(exist_ok=True)

    weapons = ["artillery_only", "helipad_only", "recon_only"]
    difficulties = [1, 2]
    colors = {
        "artillery_only": ARTILLERY_COLOR,
        "helipad_only": HELICOPTER_COLOR,
        "recon_only": RECON_PLANE_COLOR
    }

    fig, axes = plt.subplots(2, 3, figsize=(18, 10), sharex=True)
    fig.suptitle("Score Distributions per Weapon and Difficulty", fontsize=16)

    for i, difficulty in enumerate(difficulties):
        for j, weapon in enumerate(weapons):
            ax = axes[i, j]
            scores = results[(difficulty, weapon)]["scores"]
            mean = results[(difficulty, weapon)]["mean"]
            variance = results[(difficulty, weapon)]["variance"]
            sd = np.sqrt(variance)
            ax.hist(scores, bins=30, color=colors[weapon], density=True)
            x = np.linspace(scores.min(), scores.max(), 200)
            y = norm.pdf(x, loc=mean, scale=sd)
            ax.plot(x, y, 'k--', linewidth=2, label=f'Normal approx.\nμ={mean:.2f}, σ={sd:.2f}')
            ax.set_title(f"{weapon}, Difficulty {difficulty}")
            ax.set_xlabel("Score")
            ax.set_ylabel("Density")
            ax.grid(axis='y', linestyle='--', alpha=0.7)
            ax.legend()

    plt.tight_layout(rect=[0, 0.03, 1, 0.95])
    plt.savefig(output_dir / "score_distributions_grid.png")
    plt.close()


def plot_sa_trajectory(progress, path="sa_trajectory_freq.png"):
    """
    Plots the trajectory of simulated annealing progress in 3D.
    Marker size represents how many times the same coordinates were visited.
    
    Parameters:
        progress: list of tuples (mean_score, (a, h, r))
        path: path to save the plot
    """
    # Extract allocations and scores
    allocations = [tuple(p[1]) for p in progress]
    mean_scores = [p[0] for p in progress]

    # Count frequency of each coordinate
    freq_counter = Counter(allocations)

    # Unique coordinates
    unique_coords = np.array(list(freq_counter.keys()))
    freq = np.array([freq_counter[coord] for coord in freq_counter.keys()])

    # Find mean score for each unique coordinate
    score_dict = {alloc: score for score, alloc in progress}
    mean_scores_unique = np.array([score_dict[tuple(coord)] for coord in unique_coords])

    a_vals = unique_coords[:, 0]
    h_vals = unique_coords[:, 1]
    r_vals = unique_coords[:, 2]

    fig = plt.figure(figsize=(12, 8))
    ax = fig.add_subplot(111, projection='3d')

    # Colormap based on mean score
    cmap = plt.get_cmap("viridis")
    norm = plt.Normalize(mean_scores_unique.min(), mean_scores_unique.max())
    colors = cmap(norm(mean_scores_unique))

    # Marker size proportional to frequency
    sizes = 50 + (freq / freq.max()) * 200  # scale sizes

    # Scatter plot
    sc = ax.scatter(a_vals, h_vals, r_vals, c=colors, s=sizes, alpha=0.8)
    ax.plot(a_vals, h_vals, r_vals, color='gray', alpha=0.3)

    ax.set_xlabel("Artillery")
    ax.set_ylabel("Helipad")
    ax.set_zlabel("Recon")
    ax.set_title("SA Progress Trajectory (Size = Frequency, Color = Mean Score)")

    # Colorbar
    mappable = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    mappable.set_array(mean_scores_unique)
    cbar = plt.colorbar(mappable, ax=ax, pad=0.1)
    cbar.set_label("Mean Score")

    plt.tight_layout()
    plt.savefig(path)
    plt.close()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        if '-base' in sys.argv:
            results = run_baseline_experiment(n_sim=1000, max_workers=None)
            save_results(results, "sim_data/baseline_results.pkl")

            print("\n=== Baseline Summary ===\n")
            for (difficulty, name), stats in results.items():
                print(
                    f"Difficulty {difficulty}, {name}: "
                    f"mean={stats['mean']:.3f}, var={stats['variance']:.3f}"
                )
        if '-grid' in sys.argv:
            results = coarse_grid_sweep(difficulty=1, n_sim=200, max_workers=None)
            save_results(results, f"sim_data/grid_sweep_d1.pkl")
            sorted_combos = sorted(results.items(), key=lambda x: x[1]["mean"], reverse=True)
            print("\n=== Top 10 Resource Combinations by Mean Score ===\n")
            for i, ((a,h,r), stats) in enumerate(sorted_combos[:10], 1):
                print(f"{i}: Artillery={a}, Helipad={h}, Recon={r} | Mean={stats['mean']:.2f}, Variance={stats['variance']:.2f}")
        if '-sa' in sys.argv:
            best_alloc, best_score, progress, cache = simulated_annealing(difficulty=2, n_sim=100, max_workers=None)
            save_results(progress, "sim_data/simulated_annealing_prog_d2.pkl")
            save_results(cache, "sim_data/simulated_annealing_cache_d2.pkl")
            print(f"Best allocation: Artillery={best_alloc[0]}, Helipad={best_alloc[1]}, Recon={best_alloc[2]}")
            print(f"Estimated mean score: {best_score:.2f}")
        if '-gibbs' in sys.argv:
            best_alloc, best_score, progress, cache = gibbs_sampling(
                difficulty=1,
                n_sim=100,
                max_workers=None,
                initial_state=(20, 20, 10),
                n_iter=100,
                seed=42
            )
            save_results(progress, "sim_data/gibbs_prog_d1.pkl")
            save_results(cache, "sim_data/gibbs_cache_d1.pkl")
            print(f"Best allocation: Artillery={best_alloc[0]}, Helipad={best_alloc[1]}, Recon={best_alloc[2]}")
            print(f"Estimated mean score: {best_score:.2f}")
    else:
        # Single weapon runs
        results = load_results()
        plot_mean_scores(results, "sim_output")
        plot_score_distributions(results, "sim_output")

        # Simulated Annealing difficulty 1
        # progress = load_results("sim_data/simulated_annealing_prog_d1.pkl")
        # plot_sa_trajectory(progress, "sim_output/sa_trajectory_d1.png")

        # Simulated Annealing difficulty 2
        # progress = load_results("sim_data/simulated_annealing_prog_d2.pkl")
        # plot_sa_trajectory(progress, "sim_output/sa_trajectory_d2.png")
