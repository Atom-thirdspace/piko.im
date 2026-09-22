(() => {
    const cursor = document.getElementById("custom-cursor");
    if (!cursor) return;

    const normalCursor = cursor.src;
    const interactiveCursor = "https://cdn.hackclub.com/01a0b45a-113d-7610-b7a2-98083b47f684/Untitled%20design%20(69).png";
    let framePending = false;
    let nextX = 0;
    let nextY = 0;

    document.addEventListener("mousemove", (event) => {
        nextX = event.clientX;
        nextY = event.clientY;
        cursor.src = event.target.closest(
            "a, button, input[type='submit'], input[type='button'], select, [role='button']"
        ) ? interactiveCursor : normalCursor;

        if (framePending) return;
        framePending = true;
        requestAnimationFrame(() => {
            cursor.style.transform = `translate3d(${nextX}px, ${nextY}px, 0)`;
            framePending = false;
        });
    });
})();