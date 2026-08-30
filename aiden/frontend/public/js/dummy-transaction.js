// Provides a dummy transaction payload for the anomaly checker.
function dummyTransaction() {
    const merchants = ["Corner Store", "MegaMart", "Unknown LLC", "Cafe 42", "QuickCash ATM"];
    return {
        id: crypto.randomUUID(),
        amount: Math.round(Math.random() * 500000) / 100,
        merchant: merchants[Math.floor(Math.random() * merchants.length)],
        date: new Date().toISOString(),
    };
}
