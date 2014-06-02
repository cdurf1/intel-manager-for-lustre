#!/bin/bash
set -x

[ -r localenv ] && . localenv

CHROMA_DIR=${CHROMA_DIR:-"$PWD/chroma/"}
CLUSTER_CONFIG=${CLUSTER_CONFIG:-"$CHROMA_DIR/chroma-manager/tests/framework/selenium/cluster_config.json"}

eval $(python $CHROMA_DIR/chroma-manager/tests/utils/json_cfg2sh.py "$CLUSTER_CONFIG")

trap "set +e; scp -r chromatest@$TEST_RUNNER:test_reports $WORKSPACE" EXIT

scp $CLUSTER_CONFIG chromatest@$TEST_RUNNER:cluster_config.json
ssh chromatest@$TEST_RUNNER <<EOC
set -ex
mkdir test_reports
source chroma_test_env/bin/activate
vncserver :1 -geometry 1024x768
export DISPLAY=\$(hostname):1

#######################################
# New UI Tests
#######################################

# Run Karma GUI unit tests (new ui)
cd \$HOME/chroma_test_env/chroma/chroma-manager/chroma_ui_new
./node_modules/karma/bin/karma start --browsers Chrome,Firefox --singleRun true --reporters dots,junit
mv test-results.xml \$HOME/test_reports/karma-test-results-new-ui.xml

# Run Sourcemap Generation Integration Test(s)
cd \$HOME/chroma_test_env/chroma/chroma-manager/chroma_ui_new
npm i
./node_modules/.bin/mjnw --reportType=junit --JUnitReportSavePath=\$HOME/test_reports/ --JUnitReportFilePrefix=srcmap-generation-results

# Run Stub Daddy Mock API Service unit tests
cd \$HOME/chroma_test_env/chroma/chroma-manager/chroma_ui_new/stub-daddy
npm i
./node_modules/.bin/mjnw --reportType=junit --JUnitReportSavePath=\$HOME/test_reports/ --JUnitReportFilePrefix=stub-daddy-results

# Run realtime module tests (new ui)
cd \$HOME/chroma_test_env/chroma/chroma-manager
cat << EOF > ./realtime/conf.json
{
  "SERVER_HTTP_URL": "https://$CHROMA_MANAGER/",
  "PRIMUS_PORT": 8888
}
EOF
cd \$HOME/chroma_test_env/chroma/chroma-manager/realtime
./node_modules/.bin/jasmine-node-chum --verbose --captureExceptions --junitreport --output \$HOME/test_reports/ ./test/ || true

# Run protractor selenium tests in Chrome and Firefox (new ui)
cd \$HOME/chroma_test_env/chroma/chroma-manager/chroma_ui_new
./node_modules/protractor/bin/protractor ./test/selenium/protractor-conf.js --seleniumServerJar=\$HOME/bin/selenium-server-standalone.jar --config=\$HOME/cluster_config.json --chromeDriver=\$HOME/bin/chromedriver || true
mv *protractor-selenium-test*.xml \$HOME/test_reports/
./node_modules/protractor/bin/protractor ./test/selenium/protractor-conf.js --seleniumServerJar=\$HOME/bin/selenium-server-standalone.jar --config=\$HOME/cluster_config.json --browser=firefox || true
mv *protractor-selenium-test*.xml \$HOME/test_reports/

#######################################
# Old UI Tests
#######################################

# Run Karma GUI unit tests (old ui)
cd \$HOME/chroma_test_env/chroma/chroma-manager/chroma_ui
./node_modules/karma/bin/karma start --browsers Chrome,Firefox --singleRun true --reporters dots,junit
mv test-results.xml \$HOME/test_reports/karma-test-results-old-ui.xml

# Run Selenium GUI Tests (old ui)
cd \$HOME/chroma_test_env/chroma/chroma-manager
CLUSTER_DATA=tests/selenium/test_data.json PATH=\$PATH:\$HOME/chroma_test_env nosetests --verbosity=2 --with-xunit --xunit-file=\$HOME/test_reports/selenium-test-results-chrome.xml --tc-format=json --tc-file=\$HOME/cluster_config.json tests/selenium/ || true
CLUSTER_DATA=tests/selenium/test_data.json PATH=\$PATH:\$HOME/chroma_test_env nosetests --verbosity=2 --with-xunit --xunit-file=\$HOME/test_reports/selenium-test-results-firefox.xml --tc-format=json --tc-file=\$HOME/cluster_config.json --tc=browser:Firefox tests/selenium/ || true
EOC

NUM_EXPECTED_TEST_REPORTS=25
NUM_TEST_REPORTS=$(ssh chromatest@$TEST_RUNNER 'ls -l test_reports' | grep -v "^total " | wc -l)
if [ $NUM_TEST_REPORTS -ne $NUM_EXPECTED_TEST_REPORTS ]; then
    echo "Incorrect number of test reports. Possible sources include a catastrophic error running one of the test suites, or adding a new test set that causes there to be an new xml file. Expected $NUM_EXPECTED_TEST_REPORTS, but found $NUM_TEST_REPORTS."
    exit 1
else
    exit 0
fi
