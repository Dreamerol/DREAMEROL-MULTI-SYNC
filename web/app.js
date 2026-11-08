
const form = document.getElementById("sync-form");
const button = document.getElementById("sync-button");
const buttonText = document.getElementById("button-text");
const statusBox = document.getElementById("sync-status");
const resultsBox = document.getElementById("sync-results");

form.addEventListener("submit", async (event) => {
    event.preventDefault();

    const email = document.getElementById("email").value.trim();
    const password = document.getElementById("password").value;

    button.disabled = true;
    buttonText.textContent = "⟳ CHECKING...";
    statusBox.textContent = "Connecting to DREAMEROL...";
    resultsBox.replaceChildren();

    try {
        const response = await fetch("/api/sync", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({ email, password })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || "Synchronization failed.");
        }

        statusBox.textContent =
            `Completed. Checked ${data.total} repositories.`;

        data.results.forEach(result => {
            const item = document.createElement("div");
            item.className = "result-item";

            item.textContent =
                `${result.repository}: ${result.status}` +
                (result.message ? ` — ${result.message}` : "");

            resultsBox.appendChild(item);
        });

    } catch (error) {
        statusBox.textContent = error.message;
    } finally {
        button.disabled = false;
        buttonText.textContent = "⟳ SYNC";
    }
});
