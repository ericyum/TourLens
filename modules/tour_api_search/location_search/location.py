get_location_js = """
async () => {
    const getPosition = () => new Promise((resolve, reject) => navigator.geolocation.getCurrentPosition(resolve, reject));
    try {
        const pos = await getPosition();
        return [pos.coords.latitude, pos.coords.longitude];
    } catch (error) { return ["오류", "위치를 가져올 수 없습니다."]; }
}
"""
