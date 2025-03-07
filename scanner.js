document.addEventListener("DOMContentLoaded", () => {
    let BASE_URL = ""; // Will be set dynamically

    const config = {
        inputStream: {
            type: "LiveStream",
            target: document.querySelector("#scanner-video"),
            constraints: {
                facingMode: "environment" // Simplified for compatibility
            }
        },
        decoder: {
            readers: ["ean_reader", "code_128_reader", "upc_reader"]
        },
        locator: {
            patchSize: "medium",
            halfSample: true
        },
        numOfWorkers: 2, // Reduced for mobile
        locate: true
    };

    const startBtn = document.getElementById("start-btn");
    const stopBtn = document.getElementById("stop-btn");
    const checkoutBtn = document.getElementById("checkout-btn");
    const clearBtn = document.getElementById("clear-btn");
    const resultDiv = document.getElementById("result");
    const statusDiv = document.getElementById("status");
    const cartBody = document.getElementById("cart-body");
    const totalDiv = document.getElementById("total");
    let isScanning = false;
    let cart = [];
    let currentStream = null; // Track the camera stream to stop it properly

    // Fetch server IP dynamically
    fetch('/api/server-ip')
        .then(response => {
            if (!response.ok) throw new Error("Failed to fetch server IP");
            return response.json();
        })
        .then(data => {
            const SERVER_IP = data.ip;
            BASE_URL = `https://${SERVER_IP}:5000`;
            statusDiv.textContent = "Server IP detected: " + SERVER_IP;
            console.log("Server IP:", SERVER_IP);
            initializeScanner();
        })
        .catch(err => {
            statusDiv.textContent = "Error fetching IP: " + err.message;
            statusDiv.classList.add("error");
            console.error("IP fetch error:", err);
        });

    function initializeScanner() {
        startBtn.addEventListener("click", () => {
            if (!isScanning) {
                statusDiv.textContent = "Requesting camera...";
                navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } })
                    .then(stream => {
                        currentStream = stream; // Store the stream
                        statusDiv.textContent = "Camera accessed!";
                        console.log("Camera stream opened:", stream);
                        startScanner(stream);
                        startBtn.style.display = "none";
                        stopBtn.style.display = "inline-block";
                    })
                    .catch(err => {
                        statusDiv.textContent = "Camera Error: " + err.message;
                        statusDiv.classList.add("error");
                        resultDiv.textContent = "Failed to access camera.";
                        console.error("Camera access error:", err);
                    });
            }
        });

        stopBtn.addEventListener("click", stopScanner);
        checkoutBtn.addEventListener("click", checkout);
        clearBtn.addEventListener("click", clearCart);
    }

    function startScanner(stream) {
        Quagga.init(config, (err) => {
            if (err) {
                resultDiv.textContent = "Scanner init error: " + err.message;
                statusDiv.textContent = "Error";
                statusDiv.classList.add("error");
                console.error("Quagga init error:", err);
                startBtn.style.display = "inline-block";
                stopBtn.style.display = "none";
                stream.getTracks().forEach(track => track.stop());
                currentStream = null;
                return;
            }
            Quagga.start();
            isScanning = true;
            resultDiv.textContent = "Scanning for barcodes...";
            statusDiv.textContent = "Scanning...";
            statusDiv.classList.remove("error", "success");
            console.log("Scanner started successfully");
        });

        Quagga.onDetected((data) => {
            const barcode = data.codeResult.code;
            resultDiv.textContent = `Detected: ${barcode}`;
            statusDiv.textContent = "Barcode detected!";
            statusDiv.classList.add("success");
            console.log("Detected barcode:", barcode, "Format:", data.codeResult.format);
            addToCart(barcode);
            stopScanner(); // Stop scanning after detection
        });

        Quagga.onProcessed((result) => {
            if (!result || !result.codeResult) {
                console.log("Processing frame: No barcode detected yet");
            }
        });
    }

    function stopScanner() {
        if (isScanning) {
            Quagga.stop();
            isScanning = false;
            if (currentStream) {
                currentStream.getTracks().forEach(track => track.stop());
                currentStream = null;
            }
            resultDiv.textContent = resultDiv.textContent || "Scanner stopped."; // Preserve last detection
            statusDiv.textContent = "Stopped - Ready for next scan";
            startBtn.style.display = "inline-block";
            stopBtn.style.display = "none";
        }
    }

    function addToCart(barcode) {
        fetch(`${BASE_URL}/api/products/barcode/${barcode}`)
            .then(response => {
                if (!response.ok && response.status !== 404) throw new Error("Server error");
                return response.json();
            })
            .then(data => {
                if (data.error) {
                    fetch(`${BASE_URL}/api/products`, {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ barcode })
                    }).then(() => console.log("New product queued"));
                    return;
                }
                const product = { barcode, name: data.name, price: data.sell_price, quantity: 1 };
                const existing = cart.find(item => item.barcode === barcode);
                if (existing) {
                    existing.quantity += 1;
                } else {
                    cart.push(product);
                }
                updateCartDisplay();
                statusDiv.textContent = "Added to cart - Ready for next scan";
                statusDiv.classList.add("success");
                statusDiv.classList.remove("error");
            })
            .catch(error => {
                resultDiv.textContent += ` | Error: ${error.message}`;
                statusDiv.textContent = "Failed";
                statusDiv.classList.add("error");
                console.error("Fetch error:", error);
            });
    }

    function updateCartDisplay() {
        cartBody.innerHTML = "";
        let total = 0;
        cart.forEach(item => {
            const subtotal = item.price * item.quantity;
            total += subtotal;
            const tr = document.createElement("tr");
            tr.innerHTML = `
                <td>${item.barcode}</td>
                <td>${item.name}</td>
                <td>$${item.price.toFixed(2)}</td>
                <td>${item.quantity}</td>
                <td>$${subtotal.toFixed(2)}</td>
            `;
            cartBody.appendChild(tr);
        });
        totalDiv.textContent = `Total: $${total.toFixed(2)}`;
    }

    function checkout() {
        if (!cart.length) {
            alert("Cart is empty!");
            return;
        }
        fetch(`${BASE_URL}/api/transaction`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ items: cart })
        })
        .then(response => {
            if (!response.ok) throw new Error("Checkout failed");
            return response.json();
        })
        .then(data => {
            showPaymentQR(data.qr_code, data.total);
            cart = [];
            updateCartDisplay();
            statusDiv.textContent = "Checkout complete";
            statusDiv.classList.add("success");
        })
        .catch(error => {
            statusDiv.textContent = "Checkout error: " + error.message;
            statusDiv.classList.add("error");
            console.error("Checkout error:", error);
        });
    }

    function showPaymentQR(qrBase64, total) {
        const popup = window.open("", "Payment", "width=300,height=400");
        popup.document.write(`
            <html>
            <body style="text-align: center; font-family: Arial;">
                <h2>Payment</h2>
                <p>Total: $${total.toFixed(2)}</p>
                <img src="data:image/png;base64,${qrBase64}" style="width: 200px; height: 200px;">
                <p>Scan with your payment app</p>
                <button onclick="window.close()">Close</button>
            </body>
            </html>
        `);
    }

    function clearCart() {
        cart = [];
        updateCartDisplay();
        statusDiv.textContent = "Cart cleared";
    }
});