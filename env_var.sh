# Bash environment variables for WebArena and related services
# Usage: source env_var.sh

export BASE_URL="http://108.214.96.13"
# Change ports as desired
export SHOPPING_PORT=7770
export SHOPPING_ADMIN_PORT=7780
export REDDIT_PORT=9999
export GITLAB_PORT=8023
export WIKIPEDIA_PORT=8888
export MAP_PORT=3000
export HOMEPAGE_PORT=4399
export RESET_PORT=7565

# webarena environment variables (change ports as needed)
export WA_SHOPPING="$BASE_URL:7770"
export WA_SHOPPING_ADMIN="$BASE_URL:7780/admin"
export WA_REDDIT="$BASE_URL:9999"
export WA_GITLAB="$BASE_URL:8023"
export WA_WIKIPEDIA="$BASE_URL:8888/wikipedia_en_all_maxi_2022-05/A/User:The_other_Kiwix_guy/Landing"
export WA_MAP="$BASE_URL:3000"
export WA_HOMEPAGE="$BASE_URL:4399"

# if your webarena instance offers the FULL_RESET feature (optional)
export WA_FULL_RESET="$BASE_URL:7565"

export SHOPPING="$BASE_URL:7770"
export SHOPPING_ADMIN="$BASE_URL:7780/admin"
export REDDIT="$BASE_URL:9999"
export GITLAB="$BASE_URL:8023"
export WIKIPEDIA="$BASE_URL:8888/wikipedia_en_all_maxi_2022-05/A/User:The_other_Kiwix_guy/Landing"
export MAP="$BASE_URL:3000"
export HOMEPAGE="$BASE_URL:4399"

export OPENAI_API_KEY=<Your openai key> 