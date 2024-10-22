from playwright.sync_api import sync_playwright, expect
from threading import Thread
import boto3
import re
from datetime import datetime

ssm_client = boto3.client('ssm')
scrap_results = []


def save_new_container_count(name, value):
    response = ssm_client.put_parameter(
        Name=name,
        Value=value,
        Type='Integer',
        Overwrite=True
    )
    return response


def get_prev_container_count(name):
    response = ssm_client.get_parameter(
        Name=name,
        WithDecryption=False
    )
    return response['Parameter']['Value']


def exclude_special_string(origin, target):
    return origin.replace(target, '')


def get_image_list(image_container):
    image_count = image_container.locator('img').count()
    image_list = []

    for j in range(image_count):
        image_locator = image_container.locator('img').nth(j)
        image_locator.wait_for(state='visible')
        image_src = image_locator.get_attribute('src')
        image_list.append(image_src)

    return image_list


def get_product_details(contents):
    # 상품 이름
    summary = contents.locator('#prod_goods_form')
    product_name = summary.locator('div.view_tit:not(.ns-icon.prod_icon)').text_content()
    product_name = exclude_special_string(product_name, '판매대기')

    # 판매 기간
    period = contents.locator(
        'div.goods_summary p:has(span:has-text("판매기간")), '
        'div.goods_summary p:has(span:has-text("판매일정")), '
        'div.goods_summary p:has(span:has-text("판매 기간")), '
        'div.goods_summary p:has(span:has-text("판매 일정"))'
    ).text_content()

    # 상품 가격
    price = summary.locator('div.pay_detail .real_price').text_content()

    return [product_name, price, period]


def get_category(product_name):
    product_name = product_name.lower()

    if "part" in product_name or "보강판" in product_name:
        return "보강판"
    elif "기판" in product_name or "pcb" in product_name:
        return "PCB"
    elif "frame" in product_name or "프레임" in product_name:
        return "FRAME"
    elif "kit" in product_name or "키트" in product_name:
        return "KIT"
    elif "keyboard" in product_name or "키보드" in product_name:
        return "키보드"
    else:
        return "키보드"


def get_iso_date(date):
    numbers = re.findall(r'\d+', date)

    if len(numbers) == 0 or len(numbers) > 6:
        raise ValueError("Invalid date format")

    current_year = datetime.now().year
    double_digit_year = current_year % 100

    if int(numbers[0]) >= double_digit_year:
        # date: 년, 월, 일, 시간, 분, 초 리스트
        date = [0] * 6
        if (len(numbers[0])) == 2:
            date[0] = 2000 + int(numbers[0])
        else:
            date[0] = int(numbers[0])

        # 그 다음 숫자부터 월, 일, 시간, 분, 초 추출
        idx = 1
        while idx < len(numbers):
            date[idx] = int(numbers[idx])
            idx += 1

    else:  # 년도 명시 안된 경우
        date = [0] * 6
        date[0] = current_year
        idx = 0

        # 첫 숫자부터 월, 일, 시간, 분, 초 추출
        while idx < len(numbers):
            date[idx + 1] = int(numbers[idx])
            idx += 1

    iso_date = f"{date[0]:04d}-{date[1]:02d}-{date[2]:02d}T{date[3]:02d}:{date[4]:02d}:{date[5]:02d}+09:00"

    return iso_date


def get_start_date(period):
    period = period.lower()
    period = exclude_special_string(period, "판매기간")
    period = exclude_special_string(period, "판매일정")
    period = period.split("~")
    start_date = ""

    if len(period) == 1 and "부터" not in period[0]:
        return start_date

    if len(period) == 1:
        start_date = period[0].strip()
    elif len(period) == 2:
        start_date = period[0].strip()
    else:
        raise ValueError("Invalid period format")

    if "부터" in start_date:
        start_date = exclude_special_string(start_date, "부터")
    elif "from" in start_date:
        start_date = exclude_special_string(start_date, "from")
    elif "start" in start_date:
        start_date = exclude_special_string(start_date, "start")

    while start_date[0] == " " or start_date[0] == ":":
        start_date = start_date[1:]

    return get_iso_date(start_date)


def get_end_date(period):
    period = period.lower()
    period = exclude_special_string(period, "판매기간")
    period = exclude_special_string(period, "판매일정")
    period = period.split("~")
    end_date = ""

    if len(period) == 1 and "까지" not in period[0] and "to" not in period[0]:
        return end_date

    if len(period) == 1:
        end_date = period[0].strip()
    elif len(period) == 2:
        end_date = period[1].strip()
    else:
        raise ValueError("Invalid period format")

    if "까지" in end_date:
        end_date = exclude_special_string(end_date, "까지")

    while end_date[0] == " " or end_date[0] == ":":
        end_date = end_date[1:]

    return get_iso_date(end_date)


def scrap(container, page):
    container.click()
    page.wait_for_selector('div.inside[doz_type="inside"]', state='visible')
    contents = page.locator('div.inside[doz_type="inside"]')

    page.wait_for_selector('div.owl-stage', state='visible')
    image_container = contents.locator('div.owl-stage')

    image_list = get_image_list(image_container)
    product_name, price, period = get_product_details(contents)

    category = get_category(product_name)
    start_date = get_start_date(period)
    end_date = get_end_date(period)

    scrap_results.append({
        "page_url": page.url,
        "product_name": product_name,
        "price": price,
        "category": category,
        "start_date": start_date,
        "end_date": end_date,
        "image": image_list
    })

    page.go_back(wait_until='domcontentloaded', timeout=0)


def check_count_changed(new_count, prev_count):
    if new_count == prev_count:
        return False
    return True


def run():
    playwright = sync_playwright().start()
    chromium = playwright.chromium
    browser = chromium.launch(headless=False,
                              args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-gpu', '--single-process'])

    page = browser.new_page()
    page.goto("https://www.swagkey.kr/47")

    # 페이지 로드 대기
    page.wait_for_load_state('domcontentloaded')

    main_container = page.locator('div.inside')

    new_container_count = int(main_container.locator('.text-brand._unit').text_content())
    # prev_container_count = get_prev_container_count('swagkey-container-count')
    # if not check_count_changed(new_container_count, prev_container_count):
    #     raise Exception("Container count is not changed")

    # save_new_container_count('swagkey-container-count', new_container_count)

    content_containers = main_container.locator('.item-overlay')
    # container_count = new_container_count - prev_container_count

    for i in range(5):
        container = content_containers.nth(i)
        expect(container).to_be_visible()

        if not container.is_visible():
            continue

        try:
            scrap(container, page)
        except Exception as e:
            print("Exception: ", e)
            continue

    page.close()
    browser.close()
    playwright.stop()


def handler(event, context):
    thread = Thread(target=run)
    thread.start()
    thread.join()
    run()

    return {
        'statusCode': 200,
        'from': 'swagkey',
        'body': scrap_results
    }


print(handler(None, None))
