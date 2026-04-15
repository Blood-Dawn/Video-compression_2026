def test_detection_not_empty():
    from src.background_subtraction.background_subtraction import BackgroundSubtractor
    import cv2

    cap = cv2.VideoCapture("/Users/ashleynm/Downloads/test_clip.mp4")
    subtractor = BackgroundSubtractor()

    detected = False

    for _ in range(50):
        ret, frame = cap.read()
        if not ret:
            break
        mask = subtractor.apply(frame)
        regions = subtractor.get_foreground_regions(mask)
        if regions:
            detected = True
            break

    cap.release()
    assert detected