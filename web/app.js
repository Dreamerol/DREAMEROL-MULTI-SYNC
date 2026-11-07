
const repositories = [
    {
        name: "Dreamerol/AI-STUDIO",
        description: "Applied AI, machine learning and data science projects.",
        status: "up-to-date"
    },
    {
        name: "Dreamerol/COMPUTER-VISION",
        description: "Computer vision experiments and OpenCV projects.",
        status: "behind"
    },
    {
        name: "Dreamerol/NEURAL-NETWORKS",
        description: "Neural network implementations and deep learning.",
        status: "up-to-date"
    },
    {
        name: "Dreamerol/PORTFOLIO",
        description: "Software engineering and AI project portfolio.",
        status: "behind"
    },
    {
        name: "Dreamerol/SNN-NEURAL-ACTIVITY",
        description: "Spiking neural networks and computational neuroscience.",
        status: "up-to-date"
    }
];

const repositoryList = document.getElementById("repository-list");
const searchInput = document.getElementById("search");
const filterSelect = document.getElementById("filter");

function renderRepositories() {
    const searchTerm = searchInput.value.toLowerCase();
    const filter = filterSelect.value;

    const filtered = repositories.filter(repo => {
        const matchesSearch =
            repo.name.toLowerCase().includes(searchTerm) ||
            repo.description.toLowerCase().includes(searchTerm);

        const matchesFilter =
            filter === "all" || repo.status === filter;

        return matchesSearch && matchesFilter;
    });

    repositoryList.innerHTML = "";

    if (filtered.length === 0) {
        repositoryList.innerHTML =
            '<p class="empty-state">No repositories found.</p>';
        return;
    }

    filtered.forEach(repo => {
        const card = document.createElement("article");
        card.className = "repo-card";

        const details = document.createElement("div");

        const name = document.createElement("h3");
        name.className = "repo-name";
        name.textContent = repo.name;

        const description = document.createElement("p");
        description.className = "repo-description";
        description.textContent = repo.description;

        details.append(name, description);

        const status = document.createElement("span");
        status.className = `repo-status ${repo.status}`;
        status.textContent = repo.status === "up-to-date"
            ? "● UP TO DATE"
            : "● BEHIND UPSTREAM";

        card.append(details, status);
        repositoryList.appendChild(card);
    });
}

function updateStatistics() {
    const total = repositories.length;
    const upToDate = repositories.filter(
        repo => repo.status === "up-to-date"
    ).length;

    const behind = repositories.filter(
        repo => repo.status === "behind"
    ).length;

    document.getElementById("total-forks").textContent = total;
    document.getElementById("up-to-date").textContent = upToDate;
    document.getElementById("behind").textContent = behind;
    document.getElementById("repo-count").textContent =
        `${total} repositories`;
}

searchInput.addEventListener("input", renderRepositories);
filterSelect.addEventListener("change", renderRepositories);

updateStatistics();
renderRepositories();

