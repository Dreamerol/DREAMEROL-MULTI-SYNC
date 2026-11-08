const form = document.getElementById("sync-form");
const tokenInput = document.getElementById("github-token");
const previewButton = document.getElementById("preview-button");
const syncButton = document.getElementById("sync-button");
const buttonText = document.getElementById("button-text");
const statusBox = document.getElementById("sync-status");
const resultsBox = document.getElementById("sync-results");

let previewReady = false;
let previewRepositories = [];
let activeToken = "";

function renderResults(results) {
    resultsBox.replaceChildren();
    results.forEach((result) => {
        const item = document.createElement("div");
        item.className = "result-item";
        item.dataset.status = result.status;
        item.textContent = `${result.repository}: ${result.status}` +
            (Number.isInteger(result.behind_by) ? ` (${result.behind_by} behind)` : "") +
            (result.message ? ` — ${result.message}` : "");
        resultsBox.appendChild(item);
    });
}

async function requestSync(payload) {
    const response = await fetch("/api/sync", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "Authorization": `Bearer ${activeToken}`
        },
        body: JSON.stringify(payload)
    });

    let data;
    try {
        data = await response.json();
    } catch {
        throw new Error("The server returned an invalid response.");
    }

    if (!response.ok) {
        const detail = typeof data.detail === "string" ? data.detail : "Synchronization failed.";
        throw new Error(detail);
    }

    return data;
}

function setBusy(isBusy, label = "Preview forks") {
    previewButton.disabled = isBusy;
    syncButton.disabled = isBusy;
    buttonText.textContent = isBusy ? label : "Preview forks";
}

form.addEventListener("submit", async (event) => {
    event.preventDefault();
    previewReady = false;
    previewRepositories = [];
    syncButton.hidden = true;
    resultsBox.replaceChildren();
    activeToken = tokenInput.value.trim();
    tokenInput.value = "";
    setBusy(true, "Checking GitHub…");
    statusBox.textContent = "Checking your GitHub token and comparing forks with upstream…";

    try {
        const data = await requestSync({ dry_run: true });
        renderResults(data.results);

        const behindResults = data.results.filter((result) => result.status === "behind");
        const upToDateCount = data.results.filter((result) => result.status === "up-to-date").length;
        const errorCount = data.results.filter((result) => result.status === "error").length;
        previewRepositories = behindResults.map((result) => result.repository);
        previewReady = previewRepositories.length > 0;
        syncButton.hidden = !previewReady;

        statusBox.textContent = `GitHub account: ${data.account}. ${behindResults.length} behind, ${upToDateCount} up to date` +
            (errorCount ? `, ${errorCount} could not be checked` : "") + ". No repositories were changed.";
        if (data.total === 0) {
            statusBox.textContent = `No fork repositories found for ${data.account}.`;
        }
    } catch (error) {
        activeToken = "";
        statusBox.textContent = error.message || "Could not connect to the server.";
    } finally {
        setBusy(false);
    }
});

syncButton.addEventListener("click", async () => {
    if (!previewReady || previewRepositories.length === 0 || !activeToken) return;

    const confirmation = window.prompt(
        `This will synchronize ${previewRepositories.length} fork(s) shown as behind. Type SYNC to continue:`
    );
    if (confirmation !== "SYNC") {
        statusBox.textContent = "Synchronization cancelled. No repositories were changed.";
        activeToken = "";
        previewReady = false;
        previewRepositories = [];
        syncButton.hidden = true;
        return;
    }

    previewReady = false;
    syncButton.hidden = true;
    setBusy(true, "Synchronizing…");
    statusBox.textContent = "Rechecking and synchronizing only the forks that are still behind…";

    try {
        const data = await requestSync({
            dry_run: false,
            confirmation: "SYNC",
            repositories: previewRepositories
        });
        renderResults(data.results);
        const synced = data.results.filter((result) => result.status === "synced").length;
        const upToDate = data.results.filter((result) => result.status === "up-to-date").length;
        const errors = data.results.filter(
            (result) => result.status === "error" || result.status === "conflict"
        ).length;
        statusBox.textContent = `Completed for ${data.account}: ${synced} synchronized, ${upToDate} already up to date` +
            (errors ? `, ${errors} failed or conflicted` : "") + ".";
    } catch (error) {
        statusBox.textContent = error.message || "Could not connect to the server.";
    } finally {
        activeToken = "";
        previewRepositories = [];
        setBusy(false);
    }
});
