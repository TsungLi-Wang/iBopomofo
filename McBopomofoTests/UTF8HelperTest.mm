// Copyright (c) 2022 and onwards The McBopomofo Authors.
//
// Permission is hereby granted, free of charge, to any person
// obtaining a copy of this software and associated documentation
// files (the "Software"), to deal in the Software without
// restriction, including without limitation the rights to use,
// copy, modify, merge, publish, distribute, sublicense, and/or sell
// copies of the Software, and to permit persons to whom the
// Software is furnished to do so, subject to the following
// conditions:
//
// The above copyright notice and this permission notice shall be
// included in all copies or substantial portions of the Software.
//
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
// EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES
// OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
// NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
// HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
// WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
// FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
// OTHER DEALINGS IN THE SOFTWARE.

#import "UTF8Helper.h"
#import <XCTest/XCTest.h>

@interface UTF8HelperTest : XCTestCase

@end

@implementation UTF8HelperTest

- (void)testGetCodePoint1 {
  std::string s = "一二三四";
  std::string r = iBopomofo::GetCodePoint(s, 2);
  XCTAssertTrue(r == "三");
}

- (void)testGetCodePoint2 {
  std::string s = "ABCD";
  std::string r = iBopomofo::GetCodePoint(s, 2);
  XCTAssertTrue(r == "C");
}

- (void)testGetCodePoint3 {
  std::string s = "11🌳1";
  std::string r = iBopomofo::GetCodePoint(s, 2);
  XCTAssertTrue(r == "🌳");
}

- (void)testGetCodePoint4 {
  std::string s = "🌳🌳1🌳";
  std::string r = iBopomofo::GetCodePoint(s, 2);
  XCTAssertTrue(r == "1");
}

@end
