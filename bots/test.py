import undetected_chromedriver as uc

driver = uc.Chrome(headless=True)
driver.get("https://mabimobi.life/")
print("Title:", driver.title)
driver.quit()